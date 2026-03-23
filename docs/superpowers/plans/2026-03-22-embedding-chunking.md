# Embedding Model Replacement & Flat-Doc Chunking Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hash-based bag-of-words embedding with Qwen3-Embedding-0.6B served by the ML service, fix flat-document paragraph chunking, batch ingestion embed calls, and migrate pgvector dimensions from 384 to 1024.

**Architecture:** The ML service gains a `/embed` endpoint that loads Qwen3-Embedding-0.6B at startup; the backend's `embeddings.py` becomes a thin HTTP client wrapper that calls this endpoint. Two modes are used: `document` (no prefix, for ingestion) and `query` (instruction prefix, for retrieval). Flat documents without `##`/`###` headers are split by paragraph instead of being stored as one unbounded section.

**Tech Stack:** Python, FastAPI, sentence-transformers (`Qwen/Qwen3-Embedding-0.6B`), `requests`, pgvector `Vector(1024)`, pytest, `unittest.mock.patch`

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `ml/inference_server.py` | Modify | Add `/embed` endpoint; load Qwen3-0.6B at startup |
| `backend/app/services/embeddings.py` | Rewrite | Replace BoW with HTTP client; keep `_tokens`, `jaccard_similarity` |
| `backend/app/services/ingestion.py` | Modify | Batch embed calls; fix flat-doc fallback |
| `backend/app/services/incident_similarity.py` | Modify | Batch `ensure_runbook_embeddings`; add `mode="query"` at retrieval |
| `backend/app/services/incident_summaries.py` | Modify | Fresh query-mode embedding for runbook retrieval |
| `backend/app/api/runbooks.py` | Modify | `mode="query"` at search endpoint |
| `backend/tools/run_rag_eval.py` | Modify | `mode="query"` at eval query |
| `backend/app/models/database.py` | Modify | `Vector(384)` → `Vector(1024)` in two columns |
| `tests/backend/conftest.py` | Modify | Add autouse fixture to patch `embed_text`/`embed_texts` in unit tests |
| `tests/backend/unit/test_embeddings.py` | Create | Unit tests for new `embed_text`/`embed_texts` HTTP client |
| `tests/backend/unit/test_ingestion.py` | Modify | Update flat-doc test; add batch-embed assertion |
| `tests/ml/test_inference_service.py` | Modify | Add tests for `/embed` endpoint |

---

### Task 1: ML Service — `/embed` endpoint

`sentence-transformers` is already in `ml/requirements.txt`. No new dependencies needed.

**Files:**
- Modify: `ml/inference_server.py`
- Modify: `tests/ml/test_inference_service.py`

- [ ] **Step 1.1: Read the existing ML service test file**

  Run: `cat -n tests/ml/test_inference_service.py`
  Understand the existing test patterns before adding new ones.

- [ ] **Step 1.2: Write failing tests for `/embed`**

  Add to `tests/ml/test_inference_service.py`:

  ```python
  from fastapi.testclient import TestClient
  from unittest.mock import MagicMock, patch
  import numpy as np

  # At module level, patch the model loading so tests don't download weights
  @pytest.fixture(autouse=True)
  def mock_embedding_model():
      """Prevent Qwen3-0.6B from loading during tests."""
      fake_model = MagicMock()
      # encode() returns a numpy array of shape (n_texts, 1024)
      fake_model.encode = MagicMock(
          side_effect=lambda texts, **kw: np.ones((len(texts), 1024), dtype=float)
      )
      with patch("ml.inference_server.embedding_model", fake_model):
          yield fake_model


  def test_embed_document_mode(client):
      resp = client.post("/embed", json={"texts": ["check redis connection"], "mode": "document"})
      assert resp.status_code == 200
      data = resp.json()
      assert "embeddings" in data
      assert len(data["embeddings"]) == 1
      assert len(data["embeddings"][0]) == 1024


  def test_embed_query_mode_applies_prefix(client, mock_embedding_model):
      """Query mode should call encode with the instruction prefix prepended."""
      resp = client.post("/embed", json={"texts": ["redis is down"], "mode": "query"})
      assert resp.status_code == 200
      # Verify the model was called with a prefixed string
      call_args = mock_embedding_model.encode.call_args[0][0]
      assert call_args[0].startswith("Instruct:")


  def test_embed_batch(client):
      texts = ["doc one", "doc two", "doc three"]
      resp = client.post("/embed", json={"texts": texts, "mode": "document"})
      assert resp.status_code == 200
      assert len(resp.json()["embeddings"]) == 3


  def test_embed_empty_list(client):
      resp = client.post("/embed", json={"texts": [], "mode": "document"})
      assert resp.status_code == 200
      assert resp.json()["embeddings"] == []


  def test_health_reports_embedding_model(client):
      resp = client.get("/health")
      assert resp.status_code == 200
      assert "embedding_model_loaded" in resp.json()
  ```

- [ ] **Step 1.3: Run tests to confirm they fail**

  ```bash
  pytest tests/ml/test_inference_service.py -v -k "embed"
  ```
  Expected: FAIL — `embedding_model` attribute not found on `inference_server`

- [ ] **Step 1.4: Implement the `/embed` endpoint in `ml/inference_server.py`**

  Add after the existing `ner_model` global:
  ```python
  from sentence_transformers import SentenceTransformer

  embedding_model: SentenceTransformer | None = None

  RUNBOOK_QUERY_INSTRUCTION = (
      "Given an incident alert or description, retrieve relevant runbook sections "
      "that help diagnose or resolve the issue"
  )


  def _apply_query_prefix(text: str) -> str:
      return f"Instruct: {RUNBOOK_QUERY_INSTRUCTION}\nQuery: {text}"
  ```

  In `load_models()`, add after the NER model block:
  ```python
  global embedding_model
  logger.info("Loading Qwen3-Embedding-0.6B...")
  try:
      import torch
      device = "mps" if torch.backends.mps.is_available() else "cpu"
      embedding_model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B", device=device)
      logger.info(f"✓ Embedding model loaded on {device}")
  except Exception as e:
      logger.error(f"Failed to load embedding model: {e}")
      logger.warning("Embedding model unavailable")
  ```

  Update the health endpoint to include:
  ```python
  "embedding_model_loaded": embedding_model is not None
  ```

  Add Pydantic models:
  ```python
  class EmbedRequest(BaseModel):
      texts: list[str]
      mode: str = "document"   # "document" | "query"

  class EmbedResponse(BaseModel):
      embeddings: list[list[float]]
  ```

  Add the endpoint:
  ```python
  @app.post("/embed", response_model=EmbedResponse)
  def embed(request: EmbedRequest):
      if embedding_model is None:
          from fastapi import HTTPException
          raise HTTPException(status_code=503, detail="Embedding model not loaded")
      texts = request.texts
      if not texts:
          return EmbedResponse(embeddings=[])
      if request.mode == "query":
          texts = [_apply_query_prefix(t) for t in texts]
      vecs = embedding_model.encode(
          texts,
          normalize_embeddings=True,
          batch_size=8,
      )
      return EmbedResponse(embeddings=vecs.tolist())
  ```

- [ ] **Step 1.5: Run tests to confirm they pass**

  ```bash
  pytest tests/ml/test_inference_service.py -v
  ```
  Expected: all PASS

- [ ] **Step 1.6: Commit**

  ```bash
  git add ml/inference_server.py tests/ml/test_inference_service.py
  git commit -m "feat(ml): add /embed endpoint with Qwen3-Embedding-0.6B"
  ```

---

### Task 2: Replace `embeddings.py` — HTTP client + keep BM25 helpers

**Critical:** After this task `embed_text()` makes HTTP calls. We add an autouse fixture to `tests/backend/conftest.py` so all existing unit tests continue to work without hitting the network.

**Files:**
- Rewrite: `backend/app/services/embeddings.py`
- Modify: `tests/backend/conftest.py`
- Create: `tests/backend/unit/test_embeddings.py`

- [ ] **Step 2.1: Write failing unit tests for the new `embed_text`/`embed_texts`**

  Create `tests/backend/unit/test_embeddings.py`:

  ```python
  """Unit tests for embeddings.py HTTP client."""
  import pytest
  from unittest.mock import patch, MagicMock

  import app.services.embeddings as emb_module
  from app.services.embeddings import embed_text, embed_texts, EMBEDDING_DIM


  def _mock_post(embeddings: list[list[float]]):
      """Helper: returns a mock requests.post that yields given embeddings."""
      mock_resp = MagicMock()
      mock_resp.raise_for_status = MagicMock()
      mock_resp.json.return_value = {"embeddings": embeddings}
      mock = MagicMock(return_value=mock_resp)
      return mock


  @pytest.mark.unit
  def test_embedding_dim_is_1024():
      assert EMBEDDING_DIM == 1024


  @pytest.mark.unit
  def test_embed_text_calls_ml_service():
      vec = [0.1] * 1024
      with patch("app.services.embeddings._requests.post", _mock_post([vec])) as mock_post:
          result = embed_text("redis connection pool exhausted")
      assert result == vec
      call_json = mock_post.call_args.kwargs["json"]
      assert call_json["mode"] == "document"
      assert call_json["texts"] == ["redis connection pool exhausted"]


  @pytest.mark.unit
  def test_embed_text_query_mode():
      vec = [0.2] * 1024
      with patch("app.services.embeddings._requests.post", _mock_post([vec])) as mock_post:
          result = embed_text("high cpu", mode="query")
      assert result == vec
      assert mock_post.call_args.kwargs["json"]["mode"] == "query"


  @pytest.mark.unit
  def test_embed_text_empty_returns_zero_vector():
      """Empty input must not call the ML service."""
      with patch("app.services.embeddings._requests.post") as mock_post:
          result = embed_text("")
      assert result == [0.0] * 1024
      mock_post.assert_not_called()


  @pytest.mark.unit
  def test_embed_texts_batches_correctly():
      """With EMBED_BATCH_SIZE=2 and 5 texts, expect 3 HTTP calls."""
      vecs = [[float(i)] * 1024 for i in range(5)]
      call_count = 0

      def fake_post(url, json, timeout):
          nonlocal call_count
          batch = json["texts"]
          start = call_count * 2
          call_count += 1
          mock_resp = MagicMock()
          mock_resp.raise_for_status = MagicMock()
          mock_resp.json.return_value = {"embeddings": vecs[start: start + len(batch)]}
          return mock_resp

      with patch("app.services.embeddings._requests.post", fake_post):
          with patch.object(emb_module, "EMBED_BATCH_SIZE", 2):
              result = embed_texts(["t1", "t2", "t3", "t4", "t5"])

      assert call_count == 3
      assert len(result) == 5


  @pytest.mark.unit
  def test_embed_texts_empty_list():
      with patch("app.services.embeddings._requests.post") as mock_post:
          result = embed_texts([])
      assert result == []
      mock_post.assert_not_called()


  @pytest.mark.unit
  def test_embed_texts_ml_service_error_raises_runtime_error():
      import requests
      with patch("app.services.embeddings._requests.post",
                 side_effect=requests.RequestException("connection refused")):
          with pytest.raises(RuntimeError, match="ML service embedding call failed"):
              embed_texts(["some text"])


  @pytest.mark.unit
  def test_jaccard_similarity_retained():
      """jaccard_similarity must still be importable — used by incident_similarity.py."""
      from app.services.embeddings import jaccard_similarity
      assert jaccard_similarity(["a", "b"], ["b", "c"]) == pytest.approx(1 / 3)


  @pytest.mark.unit
  def test_tokens_retained():
      """_tokens must still be importable — used by incident_similarity.py."""
      from app.services.embeddings import _tokens
      tokens = _tokens("Redis connection pool exhausted")
      assert "redis" in tokens
      assert "connection" in tokens
  ```

- [ ] **Step 2.2: Run tests to confirm they fail**

  ```bash
  pytest tests/backend/unit/test_embeddings.py -v
  ```
  Expected: FAIL — `EMBEDDING_DIM` is 384, `embed_texts` doesn't exist, etc.

- [ ] **Step 2.3: Rewrite `backend/app/services/embeddings.py`**

  Replace the entire file with:

  ```python
  """
  Embedding client for OpsRelay.

  Calls the ML service /embed endpoint (Qwen3-Embedding-0.6B).
  Retains _tokens and jaccard_similarity for BM25 keyword scoring in incident_similarity.py.
  """
  from __future__ import annotations

  import os
  import re
  from typing import Iterable, List

  import requests as _requests

  EMBEDDING_DIM = 1024
  EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "8"))
  EMBED_TIMEOUT = int(os.getenv("EMBED_TIMEOUT", "60"))
  ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://localhost:8001")

  _TOKEN_RE = re.compile(r"[a-z0-9_]+")
  _STOPWORDS = {
      "a", "about", "above", "across", "after", "again", "against", "all",
      "almost", "alone", "along", "already", "also", "although", "always", "am",
      "among", "an", "and", "another", "any", "are", "around", "as", "at",
      "back", "be", "became", "because", "been", "before", "being", "between",
      "but", "by", "can", "cannot", "could", "do", "done", "down", "each",
      "even", "every", "few", "for", "from", "get", "give", "go", "had", "has",
      "have", "he", "her", "here", "him", "his", "how", "i", "if", "in",
      "into", "is", "it", "its", "just", "keep", "last", "less", "made",
      "many", "may", "me", "might", "more", "most", "move", "much", "must",
      "my", "neither", "never", "next", "no", "nobody", "none", "nor", "not",
      "nothing", "now", "of", "off", "often", "on", "once", "one", "only",
      "or", "other", "our", "out", "over", "own", "per", "please", "put",
      "rather", "re", "same", "see", "seem", "seems", "several", "she",
      "should", "since", "so", "some", "still", "such", "take", "than", "that",
      "the", "their", "them", "then", "there", "these", "they", "this",
      "those", "though", "through", "thus", "to", "too", "toward", "two",
      "un", "under", "until", "up", "upon", "us", "very", "via", "was", "we",
      "well", "were", "what", "when", "where", "whether", "which", "while",
      "who", "whom", "why", "will", "with", "within", "without", "would",
      "yet", "you", "your",
  }


  def _tokens(text: str) -> List[str]:
      if not text:
          return []
      return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


  def jaccard_similarity(tokens_a: Iterable[str], tokens_b: Iterable[str]) -> float:
      set_a = set(tokens_a)
      set_b = set(tokens_b)
      if not set_a and not set_b:
          return 0.0
      return len(set_a & set_b) / float(len(set_a | set_b))


  def embed_texts(texts: List[str], mode: str = "document") -> List[List[float]]:
      """Batch embed via ML service. mode='document' for ingestion, 'query' for retrieval."""
      if not texts:
          return []
      results: List[List[float]] = []
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
      """Embed a single text. Returns zero vector for empty input."""
      if not text or not text.strip():
          return [0.0] * EMBEDDING_DIM
      return embed_texts([text], mode=mode)[0]
  ```

- [ ] **Step 2.4: Add autouse fixture to patch embed_text in unit tests**

  Add to `tests/backend/conftest.py`:

  ```python
  from unittest.mock import patch

  @pytest.fixture(autouse=True)
  def patch_embed_text(request):
      """
      Auto-patch embed_text/embed_texts for unit tests so they don't call the ML service.
      Integration tests are excluded — they manage their own DB state and may need
      real (or explicitly mocked) embeddings.

      embed_texts uses a side_effect so it scales with input size — returning
      [fake_vec] * len(texts) regardless of batch count. This prevents mismatched
      zip() calls when upsert_markdown_document embeds multiple chunks at once.
      """
      if "unit" not in request.keywords:
          yield
          return
      fake_vec = [0.1] * 1024

      def _fake_embed_texts(texts, mode="document"):
          return [fake_vec for _ in texts]

      with patch("app.services.embeddings.embed_texts", side_effect=_fake_embed_texts) as _mock, \
           patch("app.services.embeddings.embed_text", return_value=fake_vec):
          yield _mock
  ```

- [ ] **Step 2.5: Run the new embeddings unit tests**

  ```bash
  pytest tests/backend/unit/test_embeddings.py -v
  ```
  Expected: all PASS

- [ ] **Step 2.6: Run all unit tests to confirm no regressions**

  ```bash
  pytest tests/ -m unit -v
  ```
  Expected: all PASS (autouse fixture covers existing unit tests)

- [ ] **Step 2.7: Commit**

  ```bash
  git add backend/app/services/embeddings.py \
          tests/backend/conftest.py \
          tests/backend/unit/test_embeddings.py
  git commit -m "feat: replace BoW embeddings with Qwen3-0.6B HTTP client"
  ```

---

### Task 3: Fix flat-doc chunking

The existing test `test_upsert_flat_doc_section_content_is_full_document` currently asserts the old (buggy) behaviour. It must be updated to assert the new correct behaviour.

**Files:**
- Modify: `backend/app/services/ingestion.py`
- Modify: `tests/backend/unit/test_ingestion.py`

- [ ] **Step 3.1: Update the flat-doc test to assert new behaviour**

  In `tests/backend/unit/test_ingestion.py`, replace `test_upsert_flat_doc_section_content_is_full_document`:

  ```python
  @pytest.mark.unit
  def test_upsert_flat_doc_chunks_have_bounded_section_content(db_session):
      """
      Flat docs (no ## / ### headers): each chunk's section_content equals its
      own content — NOT the full document. This prevents unbounded parent-doc
      text from being injected into LLM prompts.
      """
      upsert_markdown_document(
          db_session,
          source_document="simple-guide.md",
          source="runbooks",
          source_uri=None,
          content=FLAT_DOC,
      )
      db_session.flush()

      chunks = (
          db_session.query(RunbookChunk)
          .filter_by(source_document="simple-guide.md", source="runbooks")
          .all()
      )
      assert chunks
      for chunk in chunks:
          # section_content must equal content, not the full document
          assert chunk.section_content == chunk.content
          assert chunk.section_header == "Simple Guide"
          # no chunk's section_content should be the full doc
          assert chunk.section_content != FLAT_DOC.strip()
  ```

  Also add a test for the large flat-doc warning:

  ```python
  @pytest.mark.unit
  def test_flat_doc_large_emits_warning(caplog):
      """Flat docs over 6000 chars should log a warning."""
      import logging
      large_flat = "Word " * 1500  # ~7500 chars, no headers
      from app.services.ingestion import chunk_markdown_structured
      with caplog.at_level(logging.WARNING, logger="app.services.ingestion"):
          chunk_markdown_structured(large_flat)
      assert any("no ## headers" in r.message for r in caplog.records)
  ```

- [ ] **Step 3.2: Run the updated flat-doc test to confirm it fails**

  ```bash
  pytest tests/backend/unit/test_ingestion.py::test_upsert_flat_doc_chunks_have_bounded_section_content -v
  ```
  Expected: FAIL — `section_content` currently equals the full document

- [ ] **Step 3.3: Fix flat-doc fallback in `backend/app/services/ingestion.py`**

  In `chunk_markdown_structured`, replace the `else` branch (currently line 151):

  ```python
  # BEFORE:
  else:
      sections = [(title, text.strip())]

  # AFTER:
  else:
      sub_chunks = _split_section(text.strip(), max_chars, overlap)
      for sub_content in sub_chunks:
          chunks.append(
              DocumentChunk(
                  content=sub_content,
                  chunk_index=len(chunks),
                  title=title,
                  section_header=title,
                  section_content=sub_content,
              )
          )
      if len(text.strip()) > 6000:
          logging.getLogger(__name__).warning(
              "Flat document (%d chars) has no ## headers — "
              "consider adding section headers for better RAG retrieval",
              len(text.strip()),
          )
      return chunks
  ```

  The `return chunks` exits before the existing `return chunks` at the end of the function, so the sections loop is bypassed for flat docs.

- [ ] **Step 3.4: Run the flat-doc tests**

  ```bash
  pytest tests/backend/unit/test_ingestion.py -v
  ```
  Expected: all PASS

- [ ] **Step 3.5: Commit**

  ```bash
  git add backend/app/services/ingestion.py tests/backend/unit/test_ingestion.py
  git commit -m "fix: flat-doc chunking splits by paragraph instead of storing whole document"
  ```

---

### Task 4: Batch ingestion embedding calls

**Files:**
- Modify: `backend/app/services/ingestion.py`
- Modify: `backend/app/services/incident_similarity.py`
- Modify: `tests/backend/unit/test_ingestion.py`

- [ ] **Step 4.1: Write a test asserting `embed_texts` is called once per document (not per chunk)**

  Add to `tests/backend/unit/test_ingestion.py`:

  ```python
  @pytest.mark.unit
  def test_upsert_calls_embed_texts_once_per_document(db_session, patch_embed_text):
      """
      embed_texts should be called once with all chunk contents batched,
      not once per chunk.
      """
      from unittest.mock import patch
      from app.services import ingestion as ing_module

      call_count = 0
      original_embed_texts = __import__(
          "app.services.embeddings", fromlist=["embed_texts"]
      ).embed_texts

      def counting_embed_texts(texts, mode="document"):
          nonlocal call_count
          call_count += 1
          return [[0.1] * 1024 for _ in texts]

      with patch.object(ing_module, "embed_texts", counting_embed_texts):
          upsert_markdown_document(
              db_session,
              source_document="queue-workers-runbook.md",
              source="runbooks",
              source_uri=None,
              content=STRUCTURED_DOC,
          )

      assert call_count == 1, f"Expected 1 batch call, got {call_count}"
  ```

- [ ] **Step 4.2: Run test to confirm it fails**

  ```bash
  pytest tests/backend/unit/test_ingestion.py::test_upsert_calls_embed_texts_once_per_document -v
  ```
  Expected: FAIL — currently embeds one chunk at a time

- [ ] **Step 4.3: Batch embed in `upsert_markdown_document` in `ingestion.py`**

  Update the import at the top of `ingestion.py` to add `embed_texts`:
  ```python
  from app.services.embeddings import embed_text, embed_texts
  ```

  In `upsert_markdown_document`, replace the per-chunk embedding loop. The current loop (around line 300) embeds inline when building each `RunbookChunk`. Refactor to:

  ```python
  # Collect texts first
  texts = [chunk.content for chunk in chunks]
  embeddings = embed_texts(texts, mode="document")

  inserted = 0
  for chunk, embedding in zip(chunks, embeddings):
      metadata = { ... }  # unchanged
      search_text = ...    # unchanged
      db.add(
          RunbookChunk(
              ...
              embedding=embedding,   # use pre-computed embedding
              ...
          )
      )
      inserted += 1
  ```

  Remove the `embedding=embed_text(chunk.content)` call from inside the loop.

- [ ] **Step 4.4: Batch `ensure_runbook_embeddings` in `incident_similarity.py`**

  Update import in `incident_similarity.py`:
  ```python
  from app.services.embeddings import embed_text, embed_texts, jaccard_similarity, _tokens
  ```

  Replace the per-chunk loop in `ensure_runbook_embeddings` (lines 55–62):

  ```python
  def ensure_runbook_embeddings(db: Session) -> None:
      chunks = db.query(RunbookChunk).filter(RunbookChunk.embedding.is_(None)).all()
      if not chunks:
          return
      texts = [" ".join([c.title or "", c.content or ""]).strip() for c in chunks]
      embeddings = embed_texts(texts, mode="document")
      for chunk, embedding in zip(chunks, embeddings):
          chunk.embedding = embedding
          db.add(chunk)
  ```

- [ ] **Step 4.5: Run all unit tests**

  ```bash
  pytest tests/ -m unit -v
  ```
  Expected: all PASS

- [ ] **Step 4.6: Commit**

  ```bash
  git add backend/app/services/ingestion.py \
          backend/app/services/incident_similarity.py \
          tests/backend/unit/test_ingestion.py
  git commit -m "perf: batch embedding calls — one request per document instead of per chunk"
  ```

---

### Task 5: Retrieval — apply `mode="query"` at all call sites

**Files:**
- Modify: `backend/app/services/incident_similarity.py`
- Modify: `backend/app/services/incident_summaries.py`
- Modify: `backend/app/api/runbooks.py`
- Modify: `backend/tools/run_rag_eval.py`
- Modify: `tests/backend/unit/test_incident_similarity.py`

- [ ] **Step 5.1: Write failing tests asserting `mode="query"` at retrieval**

  Add to `tests/backend/unit/test_incident_similarity.py`:

  ```python
  @pytest.mark.unit
  def test_ensure_incident_embedding_uses_query_mode():
      """ensure_incident_embedding must call embed_text with mode='query'."""
      from unittest.mock import patch, MagicMock
      from app.services.incident_similarity import ensure_incident_embedding
      from app.models import Incident, Alert

      incident = MagicMock(spec=Incident)
      incident.title = "Redis down"
      incident.summary = None
      incident.affected_services = []

      db = MagicMock()
      db.add = MagicMock()

      with patch("app.services.incident_similarity.embed_text",
                 return_value=[0.1] * 1024) as mock_embed:
          ensure_incident_embedding(db, incident, [])

      mock_embed.assert_called_once()
      _, kwargs = mock_embed.call_args
      assert kwargs.get("mode") == "query", "ensure_incident_embedding must use mode='query'"
  ```

- [ ] **Step 5.2: Run test to confirm it fails**

  ```bash
  pytest tests/backend/unit/test_incident_similarity.py::test_ensure_incident_embedding_uses_query_mode -v
  ```
  Expected: FAIL — currently no mode argument is passed

- [ ] **Step 5.3: Update `incident_similarity.py` — query mode for `ensure_incident_embedding`**

  Line 49: change `embed_text(text)` to `embed_text(text, mode="query")`:

  ```python
  def ensure_incident_embedding(...) -> List[float]:
      text = build_incident_text(incident, alerts, include_summary=include_summary)
      embedding = embed_text(text, mode="query")   # was: embed_text(text)
      incident.incident_embedding = embedding
      db.add(incident)
      return embedding
  ```

- [ ] **Step 5.4: Update `incident_similarity.py` — query mode for vector search path**

  Find the `find_similar_runbook_chunks` function. Locate where an embedding is built from query text for the pgvector search. Change to `mode="query"`. (Check around line 240–260 for `embed_text(query_text)` or `embed_text(text)`.)

- [ ] **Step 5.5: Update `incident_summaries.py` — fresh query embedding for runbook retrieval**

  In `summarize_incident()` (lines 147–153), replace:

  ```python
  # BEFORE:
  query_text = build_incident_text(incident, alerts, include_summary=False)
  runbook_chunks = find_similar_runbook_chunks(
      db,
      incident.incident_embedding,
      query_text,
      limit=limit_runbook,
  )

  # AFTER:
  query_text = build_incident_text(incident, alerts, include_summary=False)
  query_embedding = embed_text(query_text, mode="query")
  runbook_chunks = find_similar_runbook_chunks(
      db,
      query_embedding,
      query_text,
      limit=limit_runbook,
  )
  ```

  Add import at the top of `incident_summaries.py`:
  ```python
  from app.services.embeddings import embed_text
  ```

- [ ] **Step 5.6: Update `runbooks.py` line 90**

  ```python
  # BEFORE:
  query_embedding = embed_text(q)

  # AFTER:
  query_embedding = embed_text(q, mode="query")
  ```

- [ ] **Step 5.7: Update `run_rag_eval.py` line 362**

  ```python
  # BEFORE:
  query_embedding = embed_text(case.question or "")

  # AFTER:
  query_embedding = embed_text(case.question or "", mode="query")
  ```

- [ ] **Step 5.8: Run all unit tests**

  ```bash
  pytest tests/ -m unit -v
  ```
  Expected: all PASS

- [ ] **Step 5.9: Commit**

  ```bash
  git add backend/app/services/incident_similarity.py \
          backend/app/services/incident_summaries.py \
          backend/app/api/runbooks.py \
          backend/tools/run_rag_eval.py \
          tests/backend/unit/test_incident_similarity.py
  git commit -m "feat: apply query-mode instruction prefix at all retrieval call sites"
  ```

---

### Task 6: Schema migration — `Vector(384)` → `Vector(1024)`

**Files:**
- Modify: `backend/app/models/database.py`

- [ ] **Step 6.1: Update vector dimensions in `database.py`**

  Find the two `Vector(384)` occurrences and change both to `Vector(1024)`:

  1. `RunbookChunk.embedding` — search for `embedding = Column(Vector(384))`
  2. `Incident.incident_embedding` — search for `incident_embedding = Column(Vector(384))`

  Also update any comment mentioning `384` dimensions in the same file to say `1024`.

- [ ] **Step 6.2: Run unit tests to confirm no regressions**

  ```bash
  pytest tests/ -m unit -v
  ```
  Expected: all PASS (unit tests use mocked embeddings, not real vectors)

- [ ] **Step 6.3: Drop and recreate the dev database**

  ```bash
  cd backend
  python init_db.py --drop --yes
  python init_db.py --seed
  ```

  Expected output includes confirmation that tables were created. pgvector may warn:
  `WARNING: ivfflat index on incident_embedding created with 0 rows — will train on first insert`
  This is harmless.

- [ ] **Step 6.4: Re-ingest runbooks**

  ```bash
  python datasets/load_sample_data.py
  python datasets/generate_runbooks.py
  ```

- [ ] **Step 6.5: Commit**

  ```bash
  git add backend/app/models/database.py
  git commit -m "feat: migrate embedding columns from Vector(384) to Vector(1024)"
  ```

---

## Post-Implementation Verification

After all tasks are complete:

- [ ] Run the full unit test suite:
  ```bash
  pytest tests/ -m unit -v
  ```

- [ ] Start services and smoke test the embed endpoint directly:
  ```bash
  docker-compose up --build
  curl -s -X POST http://localhost:8001/embed \
    -H "Content-Type: application/json" \
    -d '{"texts": ["redis connection pool exhausted"], "mode": "document"}' \
    | python -m json.tool | grep -c "0\."
  # Expected: 1024 values in the embedding
  ```

- [ ] Verify health endpoint reports both models loaded:
  ```bash
  curl -s http://localhost:8001/health | python -m json.tool
  # Expected: "ner_model_loaded": true, "embedding_model_loaded": true
  ```

- [ ] Run RAG evals to confirm quality improvement over BoW baseline:
  ```bash
  cd backend
  python tools/run_rag_eval.py --dataset ../datasets/evals/rag_eval_cases.jsonl --limit 5
  ```
