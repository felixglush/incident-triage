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
- Adding pgvector IVFFlat/HNSW indexes (no indexes exist today; can be added later)
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
Request:  { "texts": ["..."], "mode": "document" | "query", "dimensions": 1024 }
Response: { "embeddings": [[...], [...]] }
```

- `mode="document"`: texts encoded as-is (no prefix). Used at ingestion time.
- `mode="query"`: texts wrapped with the fixed instruction prefix before encoding. Used at retrieval time.

**Instruction constant (inside ML service, never exposed to backend):**
```python
RUNBOOK_QUERY_INSTRUCTION = (
    "Given an incident alert or description, retrieve relevant runbook sections "
    "that help diagnose or resolve the issue"
)

def _apply_query_prefix(text: str) -> str:
    return f"Instruct: {RUNBOOK_QUERY_INSTRUCTION}\nQuery: {text}"
```

**Pydantic models:**
```python
class EmbedRequest(BaseModel):
    texts: list[str]
    mode: str = "document"   # "document" | "query"
    dimensions: int = 1024

class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
```

The `dimensions` parameter passes through to `SentenceTransformer.encode(output_value=..., normalize_embeddings=True)` via the model's MRL support. Default 1024 (full dims).

Health check updated to report embedding model load status.

---

### 2. Backend — `embeddings.py` replacement

The BoW implementation is replaced entirely with an HTTP client wrapper. The public interface (`embed_text`, `embed_texts`, `EMBEDDING_DIM`) is preserved so call sites require minimal changes.

```python
# backend/app/services/embeddings.py

EMBEDDING_DIM = 1024
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "8"))
EMBED_TIMEOUT = int(os.getenv("EMBED_TIMEOUT", "60"))
ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://localhost:8001")

def embed_texts(texts: list[str], mode: str = "document") -> list[list[float]]:
    """Batch embed. Splits into batches of EMBED_BATCH_SIZE internally."""
    results = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        try:
            response = httpx.post(
                f"{ML_SERVICE_URL}/embed",
                json={"texts": batch, "mode": mode},
                timeout=EMBED_TIMEOUT,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"ML service embedding call failed: {exc}") from exc
        results.extend(response.json()["embeddings"])
    return results

def embed_text(text: str, mode: str = "document") -> list[float]:
    return embed_texts([text], mode=mode)[0]
```

`httpx` replaces the old `hashlib`/`math` imports. `httpx` is already a backend dependency (used in tasks.py for ML service calls).

---

### 3. Ingestion batching — `ingestion.py`

`upsert_markdown_document` restructured to embed all chunks in a single batched call per document:

```python
# Before (one call per chunk):
embedding=embed_text(chunk.content)

# After (one batched call per document):
texts = [chunk.content for chunk in chunks]
embeddings = embed_texts(texts, mode="document")
for chunk, embedding in zip(chunks, embeddings):
    db.add(RunbookChunk(..., embedding=embedding))
```

`ensure_runbook_embeddings` in `incident_similarity.py` batched similarly:

```python
chunks = db.query(RunbookChunk).filter(RunbookChunk.embedding.is_(None)).all()
if not chunks:
    return
texts = [" ".join([c.title or "", c.content or ""]).strip() for c in chunks]
embeddings = embed_texts(texts, mode="document")
for chunk, embedding in zip(chunks, embeddings):
    chunk.embedding = embedding
    db.add(chunk)
```

---

### 4. Retrieval — query mode

All retrieval paths that build a query embedding switch to `mode="query"`:

- `incident_similarity.py`: `ensure_incident_embedding` and the vector search query path pass `mode="query"` when embedding incident/query text
- `ingestion.py`: document embedding stays `mode="document"` (default, no change)

This is the only functional behaviour change at call sites.

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
    if len(text.strip()) > 3000:
        logger.warning(
            "Flat document (%d chars) has no ## headers — "
            "consider adding section headers for better RAG retrieval",
            len(text.strip()),
        )
    return chunks
```

`section_content = content` for flat docs is intentional: the small-to-big pattern only adds value when a meaningful parent section boundary exists. For flat docs, the child chunk is the most coherent unit available.

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

**Migration steps** (dev):
```bash
cd backend
python init_db.py --drop --yes   # drops and recreates schema
python init_db.py --seed         # optional seed data
python datasets/load_sample_data.py   # re-ingest runbooks
python datasets/generate_runbooks.py
```

No pgvector index exists today, so no index recreation needed.

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
  find_similar_runbook_chunks(query_text)
    → embed_text(query_text, mode="query")
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

## Testing

- Unit tests for `embed_texts` mock the ML service HTTP call (same pattern as existing ML service mocks in `conftest.py`)
- Unit tests for `chunk_markdown_structured` add flat-doc cases asserting `section_content == content` per chunk and no unbounded parent text
- Integration tests for `upsert_markdown_document` verify embeddings are stored with dimension 1024
- Existing retrieval tests updated to assert `mode="query"` is passed when building query embeddings
