# Embedding Model Replacement & Flat-Doc Chunking Fix

**Date:** 2026-03-22
**Status:** Approved

## Problem Statement

Three related issues in the current RAG pipeline:

1. `embed_text()` in `embeddings.py` is a hash-based bag-of-words vectoriser — a placeholder that was never replaced with a real embedding model. All runbook embeddings are therefore low quality.
2. The flat-doc fallback in `chunk_markdown_structured` (documents with no `##`/`###` headers) treats the entire document as a single `section_content`, causing potentially unbounded parent text to be injected into every LLM prompt for that document.
3. Ingestion embeds chunks one at a time (one HTTP call per chunk), which will be inefficient once a real model is wired in.

## Goals

- Replace BoW embeddings with `Qwen3-Embedding-0.6B` via the existing ML service
- Fix flat-doc chunking so headerless documents are split by paragraph, not stored whole
- Batch embedding calls to the ML service (default batch size 8)
- Migrate vector dimensions from 384 to 1024 (full Qwen3-0.6B native output)

## Out of Scope

- Embedding parent `section_content` (a future retrieval quality improvement)
- Adding pgvector IVFFlat/HNSW indexes to `RunbookChunk` (none exist today)
- Changing the classification or entity extraction paths in the ML service

---

## Design

### 1. ML Service — `/embed` endpoint

`ml/inference_server.py` gains a new endpoint. `Qwen3-Embedding-0.6B` is loaded once at startup alongside the existing NER model.

**Device selection at startup:**
```python
import torch
device = "mps" if torch.backends.mps.is_available() else "cpu"
embedding_model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B", device=device)
```

**Endpoint:**
```
POST /embed
Request:  { "texts": ["..."], "mode": "document" | "query" }
Response: { "embeddings": [[...], [...]] }
```

- `mode="document"`: texts encoded as-is (no prefix). Used at ingestion time.
- `mode="query"`: texts wrapped with the fixed instruction prefix before encoding. Used at retrieval time.

The model always outputs full 1024-dim embeddings (no MRL truncation). The `dimensions` parameter is not exposed — if variable-dimension support is needed it can be added later.

**Instruction constant (inside ML service, never exposed to backend):**
```python
RUNBOOK_QUERY_INSTRUCTION = (
    "Given an incident alert or description, retrieve relevant runbook sections "
    "that help diagnose or resolve the issue"
)

def _apply_query_prefix(text: str) -> str:
    return f"Instruct: {RUNBOOK_QUERY_INSTRUCTION}\nQuery: {text}"
```

**Encoding:**
```python
@app.post("/embed", response_model=EmbedResponse)
def embed(request: EmbedRequest):
    texts = request.texts
    if request.mode == "query":
        texts = [_apply_query_prefix(t) for t in texts]
    embeddings = embedding_model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=8,
    ).tolist()
    return EmbedResponse(embeddings=embeddings)
```

**Pydantic models:**
```python
class EmbedRequest(BaseModel):
    texts: list[str]
    mode: str = "document"   # "document" | "query"

class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
```

Health check updated to report embedding model load status alongside NER model.

---

### 2. Backend — `embeddings.py` replacement

The BoW implementation is replaced with an HTTP client wrapper using `requests` (already in `backend/requirements.txt:24`). **Do not use `httpx`** — it is dev-only in this project.

The public interface (`embed_text`, `embed_texts`, `EMBEDDING_DIM`) is preserved. `jaccard_similarity` and `_tokens` — used by `incident_similarity.py` for BM25 keyword scoring — are **retained in `embeddings.py`** unchanged.

```python
# backend/app/services/embeddings.py

import os
import requests as _requests
from typing import List

EMBEDDING_DIM = 1024
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "8"))
EMBED_TIMEOUT = int(os.getenv("EMBED_TIMEOUT", "60"))
ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://localhost:8001")


def embed_texts(texts: List[str], mode: str = "document") -> List[List[float]]:
    """Batch embed. Splits into batches of EMBED_BATCH_SIZE internally.
    mode='document' for ingestion, mode='query' for retrieval.
    """
    if not texts:
        return []
    results = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        try:
            response = _requests.post(
                f"{ML_SERVICE_URL}/embed",
                json={"texts": batch, "mode": mode},
                timeout=EMBED_TIMEOUT,
            )
            response.raise_for_status()
        except _requests.RequestException as exc:
            raise RuntimeError(f"ML service embedding call failed: {exc}") from exc
        results.extend(response.json()["embeddings"])
    return results


def embed_text(text: str, mode: str = "document") -> List[float]:
    """Embed a single text. Returns a zero vector if text is empty."""
    if not text or not text.strip():
        return [0.0] * EMBEDDING_DIM
    return embed_texts([text], mode=mode)[0]


# --- retain unchanged below this line ---
# jaccard_similarity, _tokens, _hash_token, _STOPWORDS, _TOKEN_RE
# (used by incident_similarity.py for BM25 keyword scoring)
```

The old `_hash_token`, `_hash_token`, `_TOKEN_RE`, `_STOPWORDS` bag-of-words helpers are **removed**. Only `_tokens` and `jaccard_similarity` are kept.

---

### 3. Ingestion batching — `ingestion.py`

`upsert_markdown_document` restructured to embed all chunks for a document in one batched call:

```python
# Before (one call per chunk):
embedding=embed_text(chunk.content)

# After (one batched call per document):
texts = [chunk.content for chunk in chunks]
embeddings = embed_texts(texts, mode="document")
for chunk, embedding in zip(chunks, embeddings):
    db.add(RunbookChunk(..., embedding=embedding))
```

`ensure_runbook_embeddings` in `incident_similarity.py` batched similarly (documents — no query prefix):

```python
chunks = db.query(RunbookChunk).filter(RunbookChunk.embedding.is_(None)).all()
if not chunks:
    return
texts = [" ".join([c.title or "", c.content or ""]).strip() for c in chunks]
embeddings = embed_texts(texts, mode="document")   # document mode: no prefix
for chunk, embedding in zip(chunks, embeddings):
    chunk.embedding = embedding
    db.add(chunk)
```

---

### 4. Retrieval — query mode call sites

Qwen3's instruction prefix must be applied when embedding query/incident text at retrieval time. All of the following call sites switch to `mode="query"`. Ingestion paths stay `mode="document"`.

| File | Location | Change |
|---|---|---|
| `incident_similarity.py` | `ensure_incident_embedding` | `embed_text(text, mode="query")` |
| `incident_similarity.py` | vector search query path | `embed_text(query_text, mode="query")` |
| `incident_summaries.py` | `find_similar_runbook_chunks` call | see note below |
| `backend/app/api/runbooks.py` | line 90, `/runbooks/search` endpoint | `embed_text(q, mode="query")` |
| `backend/tools/run_rag_eval.py` | line 362, eval query | `embed_text(case.question or "", mode="query")` |

**`incident_summaries.py` — important:** Currently this passes `incident.incident_embedding` (the stored incident vector) directly to `find_similar_runbook_chunks` as the query vector. This stored embedding was computed at incident creation time in document mode. For runbook retrieval the query vector must be in query mode. Fix: compute a fresh embedding from `query_text` at retrieval time:

```python
# in summarize_incident(), replace:
runbook_chunks = find_similar_runbook_chunks(
    db, incident.incident_embedding, query_text, limit=limit_runbook
)

# with:
query_embedding = embed_text(query_text, mode="query")
runbook_chunks = find_similar_runbook_chunks(
    db, query_embedding, query_text, limit=limit_runbook
)
```

The stored `incident.incident_embedding` is still used for incident-to-incident similarity (`find_similar_incidents`), where both sides are stored at the same mode — no change needed there.

---

### 5. Flat-doc chunking fix — `ingestion.py`

The current fallback for documents without `##`/`###` headers:

```python
# Current (buggy):
else:
    sections = [(title, text.strip())]  # entire doc = one section_content
```

Replaced with direct paragraph splitting that bypasses the sections loop:

```python
else:
    # Flat doc: split on paragraphs. section_content = content (no parent boundary exists).
    sub_chunks = _split_section(text.strip(), max_chars, overlap)
    for sub_content in sub_chunks:
        chunks.append(DocumentChunk(
            content=sub_content,
            chunk_index=len(chunks),
            title=title,
            section_header=title,
            section_content=sub_content,
        ))
    if len(text.strip()) > 6000:
        logger.warning(
            "Flat document (%d chars) has no ## headers — "
            "consider adding section headers for better RAG retrieval",
            len(text.strip()),
        )
    return chunks
```

`section_content = content` for flat docs is intentional: the small-to-big pattern only adds value when a meaningful parent section boundary exists. For flat docs, the child chunk is the most coherent unit available.

Warning threshold is 6000 chars, consistent with the existing `chunk_markdown_structured` large-section warning.

---

### 6. Schema migration

Two column changes in `backend/app/models/database.py`:

```python
# RunbookChunk
embedding = Column(Vector(1024))          # was Vector(384)

# Incident
incident_embedding = Column(Vector(1024)) # was Vector(384)
```

`EMBEDDING_DIM` in `embeddings.py` updated to `1024`.

Note: `Incident.incident_embedding` has an existing IVFFlat index (`lists=100`) defined in `database.py`. After `--drop --yes` recreation on an empty table, pgvector will create the index on zero rows — this is harmless but pgvector will warn that IVFFlat requires training data. The index becomes effective once incidents are inserted. No action needed beyond the normal re-ingest steps.

**Migration steps** (dev):
```bash
cd backend
python init_db.py --drop --yes        # drops and recreates schema
python init_db.py --seed              # optional seed data
python datasets/load_sample_data.py   # re-ingest runbooks
python datasets/generate_runbooks.py
```

---

## Data Flow After Change

```
Ingestion:
  upsert_markdown_document()
    → chunk_markdown_structured()  [child chunks ≤ 1000 chars; flat-doc fix applied]
    → embed_texts(contents, mode="document")
      → ML service POST /embed [Qwen3-0.6B, no prefix, batches of 8]
    → RunbookChunk(embedding=Vector(1024))  → pgvector

Retrieval:
  summarize_incident() / find_similar_runbook_chunks()
    → embed_text(query_text, mode="query")   [fresh, not stored embedding]
      → ML service POST /embed [Qwen3-0.6B, instruction prefix applied]
    → pgvector L2 distance search on Vector(1024)
    → hybrid score (vector + BM25)
    → returns section_content as LLM context
```

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `EMBED_BATCH_SIZE` | `8` | Chunks per ML service call |
| `EMBED_TIMEOUT` | `60` | HTTP timeout (seconds) for embed calls |
| `ML_SERVICE_URL` | `http://localhost:8001` | Already exists; no change |

---

## Implementation Notes

- `embed_texts` / `embed_text` are synchronous (using `requests`). Do not call from async FastAPI route handlers without wrapping in `run_in_executor`. Current call sites are all sync (Celery tasks, sync route handlers) — safe as-is.
- If the ML service is unavailable, embedding calls raise `RuntimeError`. This is consistent with current ML service call behaviour in `tasks.py` (no retry at the embedding level; Celery task-level retry handles it).
- `embed_text("")` returns a zero vector without hitting the ML service, matching the prior BoW behaviour for empty input.

---

## Testing

- Unit tests for `embed_texts` mock the ML service HTTP call using `responses` or `unittest.mock.patch` (same pattern as existing ML service mocks in `conftest.py`)
- Unit tests for `chunk_markdown_structured` add flat-doc cases asserting `section_content == content` per chunk and that no chunk's `section_content` exceeds `max_chars + overlap`
- Integration tests for `upsert_markdown_document` verify embeddings are stored with dimension 1024
- Existing retrieval tests updated to assert `mode="query"` is passed when building query embeddings
- RAG eval (`tools/run_rag_eval.py`) re-run after migration to confirm retrieval quality improvement over BoW baseline
