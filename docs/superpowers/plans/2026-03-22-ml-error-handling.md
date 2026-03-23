# ML Service Error Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all ML service embedding failures non-fatal by catching `RuntimeError` at the right boundary in each context, degrading to BM25-only retrieval for user-facing routes and continuing with `None` embedding for background tasks.

**Architecture:** Three contexts get three behaviors — alert pipeline Celery tasks catch embedding failure and continue (incident stored with `incident_embedding=None`); user-facing routes catch failure and pass `query_embedding=None` to trigger BM25-only retrieval; ingestion keeps hard-failing (Celery retry is correct for runbook chunk embedding). The foundation is making `find_similar_runbook_chunks` accept `Optional[List[float]]` as its query embedding, skipping the pgvector path when `None`.

**Tech Stack:** Python, SQLAlchemy, Celery, FastAPI, pgvector, pytest, `unittest.mock`

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `backend/app/services/incident_similarity.py` | Modify | Accept `Optional[List[float]]` in `find_similar_runbook_chunks`; skip vector path when `None` |
| `backend/app/workers/tasks.py` | Modify | Catch `RuntimeError` from `ensure_incident_embedding`; continue with `None` embedding |
| `backend/app/services/incident_summaries.py` | Modify | Catch `RuntimeError` from `embed_text`; pass `None` to `find_similar_runbook_chunks` |
| `backend/app/api/runbooks.py` | Modify | Catch `RuntimeError` from `embed_text`; pass `None` to `find_similar_runbook_chunks` |
| `tests/backend/unit/test_incident_similarity.py` | Modify | Add test for `find_similar_runbook_chunks` with `query_embedding=None` |
| `tests/backend/unit/test_celery_tasks.py` | Modify | Add test for `process_alert` when embedding raises |
| `tests/backend/unit/test_incident_summaries.py` | Modify | Add test for `summarize_incident` when embedding raises |
| `tests/backend/unit/test_incident_similarity.py` | Modify | Add test for `/runbooks/search` when embedding raises (call route function directly) |

---

### Task 1: `find_similar_runbook_chunks` accepts `None` query embedding

This is the foundation — all other tasks depend on this being safe to call with `None`.

**Files:**
- Modify: `backend/app/services/incident_similarity.py:231-237` (signature)
- Modify: `backend/app/services/incident_similarity.py:248-262` (pgvector block)
- Test: `tests/backend/unit/test_incident_similarity.py`

- [ ] **Step 1.1: Read the function signature and pgvector block**

  Read `backend/app/services/incident_similarity.py` lines 231–300 to understand the current vector search block before changing it.

- [ ] **Step 1.2: Write failing test**

  Add to `tests/backend/unit/test_incident_similarity.py`:

  ```python
  @pytest.mark.unit
  def test_find_similar_runbook_chunks_none_embedding_skips_vector_path():
      """When query_embedding is None, l2_distance must never be called — BM25 runs instead."""
      from app.models import RunbookChunk as RC
      section_content = "Full section content for BM25 fallback test."
      chunk = _make_chunk(
          id=50,
          source_document="bm25-runbook.md",
          title="BM25 Runbook",
          content="redis memory exhaustion resolution steps",
          section_header="Redis OOM",
          section_content=section_content,
      )

      db = _mock_db_no_pgvector([(chunk, 0.8)])

      # Patch HAS_PGVECTOR=True so the guard condition is actually exercised.
      # Also spy on l2_distance to assert it is never called when embedding is None.
      with patch("app.services.incident_similarity.HAS_PGVECTOR", True), \
           patch.object(RC.embedding, "l2_distance") as mock_l2_distance:
          results = find_similar_runbook_chunks(
              db=db,
              query_embedding=None,   # None: vector path must be skipped entirely
              query_text="redis memory exhaustion",
              limit=5,
              min_score=0.0,
          )

      # The guard must have prevented l2_distance from being called
      mock_l2_distance.assert_not_called()
      # BM25 still ran and returned results
      assert len(results) == 1
      assert results[0]["context"] == section_content
  ```

- [ ] **Step 1.3: Run test to confirm it fails**

  ```bash
  cd /Users/felix/incident-triage
  pytest tests/backend/unit/test_incident_similarity.py::test_find_similar_runbook_chunks_none_embedding_skips_vector_path -v
  ```
  Expected: FAIL — `l2_distance` is called (guard missing) and/or results are wrong.

- [ ] **Step 1.4: Update the function signature**

  In `backend/app/services/incident_similarity.py`, change the `find_similar_runbook_chunks` signature from:

  ```python
  def find_similar_runbook_chunks(
      db: Session,
      query_embedding: List[float],
      query_text: str,
      limit: int = 5,
      min_score: float = MIN_SCORE,
  ) -> List[Dict[str, Any]]:
  ```

  to:

  ```python
  def find_similar_runbook_chunks(
      db: Session,
      query_embedding: Optional[List[float]],
      query_text: str,
      limit: int = 5,
      min_score: float = MIN_SCORE,
  ) -> List[Dict[str, Any]]:
  ```

  Add `Optional` to the typing import at the top of the file if not already present:
  ```python
  from typing import Any, Dict, List, Optional
  ```
  (Check the current import line — `Optional` is not there today.)

- [ ] **Step 1.5: Guard the pgvector block**

  Inside `find_similar_runbook_chunks`, find the `if HAS_PGVECTOR:` block. Change:

  ```python
  if HAS_PGVECTOR:
      try:
          distance = RunbookChunk.embedding.l2_distance(query_embedding)
  ```

  to:

  ```python
  if HAS_PGVECTOR and query_embedding is not None:
      try:
          distance = RunbookChunk.embedding.l2_distance(query_embedding)
  ```

- [ ] **Step 1.6: Run test to confirm it passes**

  ```bash
  cd /Users/felix/incident-triage
  pytest tests/backend/unit/test_incident_similarity.py -v -m unit
  ```
  Expected: all PASS including the new test.

- [ ] **Step 1.7: Commit**

  ```bash
  cd /Users/felix/incident-triage
  git add backend/app/services/incident_similarity.py \
          tests/backend/unit/test_incident_similarity.py
  git commit -m "feat: find_similar_runbook_chunks accepts None query_embedding, skips vector path"
  ```

---

### Task 2: Alert pipeline — soft-fail embedding in `process_alert`

When the ML service `/embed` endpoint is unavailable, `ensure_incident_embedding` propagates `RuntimeError` causing a Celery retry — inconsistent with how `/classify` and `/extract-entities` handle failures. Fix: catch at the task boundary and continue with `incident_embedding=None`.

**Files:**
- Modify: `backend/app/workers/tasks.py:154-157`
- Test: `tests/backend/unit/test_celery_tasks.py`

- [ ] **Step 2.1: Read the current task code**

  Read `backend/app/workers/tasks.py` lines 140–180 to understand where `ensure_incident_embedding` is called and what surrounds it.

- [ ] **Step 2.2: Write failing test**

  Add to the `TestProcessAlertTask` class in `tests/backend/unit/test_celery_tasks.py`:

  ```python
  @pytest.mark.unit
  @pytest.mark.celery
  @pytest.mark.database
  @pytest.mark.no_embed_patch
  @mock.patch('app.workers.tasks.requests.post')
  def test_process_alert_embedding_failure_does_not_retry(self, mock_post, db_session, celery_app):
      """Embedding failure must not cause a Celery retry — incident stored with embedding=None."""
      configure_factories(db_session)

      # /classify and /extract-entities return valid responses
      def side_effect(url, **kwargs):
          resp = mock.Mock()
          resp.raise_for_status = mock.Mock()
          if "/classify" in url:
              resp.json.return_value = {"severity": "warning", "team": "backend", "confidence": 0.9}
          elif "/extract-entities" in url:
              resp.json.return_value = {"entities": {}}
          return resp

      mock_post.side_effect = side_effect

      alert = AlertFactory()
      db_session.commit()

      # Make embed_text raise RuntimeError — simulates ML service /embed returning 503
      with mock.patch(
          "app.services.incident_similarity.embed_text",
          side_effect=RuntimeError("ML service embedding call failed: 503"),
      ):
          result = process_alert.delay(alert.id)

      assert result.successful(), f"Task must not retry/fail: {result.result}"

      db_session.refresh(alert)
      assert alert.incident_id is not None, "Alert must still be grouped into an incident"

      incident = db_session.query(Incident).filter_by(id=alert.incident_id).first()
      assert incident is not None
      assert incident.incident_embedding is None, \
          "incident_embedding must be None when embedding fails"
  ```

  Make sure `Incident` is imported at the top of the test file. Check the existing imports — add if missing:
  ```python
  from app.models import Incident
  ```

- [ ] **Step 2.3: Run test to confirm it fails**

  ```bash
  cd /Users/felix/incident-triage
  pytest "tests/backend/unit/test_celery_tasks.py::TestProcessAlert::test_process_alert_embedding_failure_does_not_retry" -v
  ```
  Expected: FAIL — task retries or raises instead of completing successfully.

- [ ] **Step 2.4: Wrap `ensure_incident_embedding` in `tasks.py`**

  Find the block calling `ensure_incident_embedding` (around line 154). Change from:

  ```python
  ensure_incident_embedding(db, incident, alerts)
  db.commit()
  ```

  to:

  ```python
  try:
      ensure_incident_embedding(db, incident, alerts)
  except RuntimeError as exc:
      logger.warning(
          "Embedding unavailable for incident %s, continuing without: %s",
          incident_id, exc,
      )
      # incident.incident_embedding stays None — retrieval falls back to BM25
  db.commit()
  ```

- [ ] **Step 2.5: Run tests**

  ```bash
  cd /Users/felix/incident-triage
  pytest tests/backend/unit/test_celery_tasks.py -v -m unit
  ```
  Expected: all PASS including the new test.

- [ ] **Step 2.6: Commit**

  ```bash
  cd /Users/felix/incident-triage
  git add backend/app/workers/tasks.py \
          tests/backend/unit/test_celery_tasks.py
  git commit -m "fix: catch embedding RuntimeError in process_alert, continue with None embedding"
  ```

---

### Task 3: User-facing routes — soft-fail embedding in summaries and search

Both `summarize_incident` and `/runbooks/search` call `embed_text` for a query embedding. If the ML service is down, they should pass `query_embedding=None` and let BM25 handle retrieval.

**Files:**
- Modify: `backend/app/services/incident_summaries.py:148-155`
- Modify: `backend/app/api/runbooks.py:88-92`
- Test: `tests/backend/unit/test_incident_summaries.py`
- Test: `tests/backend/unit/test_incident_similarity.py` (runbooks search test goes here — no dedicated runbooks API unit test file exists)

- [ ] **Step 3.1: Read both files**

  Read `backend/app/services/incident_summaries.py` lines 117–160 and `backend/app/api/runbooks.py` lines 1–100.

- [ ] **Step 3.2: Write failing test for `summarize_incident`**

  Add to `tests/backend/unit/test_incident_summaries.py`:

  ```python
  @pytest.mark.unit
  @pytest.mark.no_embed_patch
  def test_summarize_incident_embedding_failure_falls_back_to_bm25(db_session):
      """When embed_text raises, summarize_incident passes None to find_similar_runbook_chunks."""
      from unittest.mock import patch, call
      from app.services.incident_summaries import summarize_incident

      with patch("app.services.incident_summaries.embed_text",
                 side_effect=RuntimeError("ML service embedding call failed")), \
           patch("app.services.incident_summaries.find_similar_runbook_chunks",
                 return_value=[]) as mock_find, \
           patch("app.services.incident_summaries.find_similar_incidents",
                 return_value=[]), \
           patch("app.services.incident_summaries.ensure_incident_embedding",
                 return_value=[0.1] * 1024):

          # Create a minimal incident in the DB so summarize_incident can find it
          from app.models import Incident, SeverityLevel, IncidentStatus
          incident = Incident(
              title="Redis OOM",
              status=IncidentStatus.OPEN,
              severity=SeverityLevel.WARNING,
          )
          db_session.add(incident)
          db_session.flush()

          # Must not raise despite embed_text failing
          summarize_incident(db_session, incident_id=incident.id)

      # find_similar_runbook_chunks must have been called with query_embedding=None
      assert mock_find.called, "find_similar_runbook_chunks must be called"
      # Second positional argument is query_embedding
      actual_embedding = mock_find.call_args[0][1]
      assert actual_embedding is None, \
          f"Expected query_embedding=None when embed_text fails, got {actual_embedding!r}"
  ```

- [ ] **Step 3.3: Write failing test for `/runbooks/search` route**

  Add to `tests/backend/unit/test_incident_similarity.py` (or wherever runbooks route logic is tested — check existing unit test files first):

  ```python
  @pytest.mark.unit
  @pytest.mark.no_embed_patch
  def test_runbook_search_embedding_failure_falls_back_to_bm25():
      """When embed_text raises in /runbooks/search, route passes None to find_similar_runbook_chunks."""
      from unittest.mock import patch
      from app.api.runbooks import search_runbooks
      from app.database import get_db

      mock_db = MagicMock()

      with patch("app.api.runbooks.embed_text",
                 side_effect=RuntimeError("ML service embedding call failed")), \
           patch("app.api.runbooks.find_similar_runbook_chunks",
                 return_value=[]) as mock_find, \
           patch("app.api.runbooks.ensure_runbook_embeddings"):

          # Call the route function directly (no HTTP overhead)
          import asyncio
          # search_runbooks is a sync route — call it directly
          search_runbooks(q="redis memory exhaustion", limit=5, db=mock_db)

      assert mock_find.called
      actual_embedding = mock_find.call_args[0][1]
      assert actual_embedding is None, \
          f"Expected query_embedding=None when embed_text fails, got {actual_embedding!r}"
  ```

  Note: Read `backend/app/api/runbooks.py` to confirm the function name (`search_runbooks` or similar) and parameter names before writing this test.

- [ ] **Step 3.4: Run tests to confirm they fail**

  ```bash
  cd /Users/felix/incident-triage
  pytest tests/backend/unit/test_incident_summaries.py -v -m unit -k "embedding_failure"
  pytest tests/backend/unit/test_incident_similarity.py -v -m unit -k "runbook_search_embedding"
  ```
  Expected: both FAIL — `RuntimeError` propagates instead of being caught.

- [ ] **Step 3.5: Wrap `embed_text` in `incident_summaries.py`**

  In `backend/app/services/incident_summaries.py`, change:

  ```python
  query_text = build_incident_text(incident, alerts, include_summary=False)
  query_embedding = embed_text(query_text, mode="query")
  runbook_chunks = find_similar_runbook_chunks(
      db,
      query_embedding,
      query_text,
      limit=limit_runbook,
  )
  ```

  to:

  ```python
  query_text = build_incident_text(incident, alerts, include_summary=False)
  try:
      query_embedding = embed_text(query_text, mode="query")
  except RuntimeError as exc:
      logger.warning(
          "Embedding unavailable for runbook retrieval on incident %s, "
          "falling back to BM25: %s",
          incident_id, exc,
      )
      query_embedding = None
  runbook_chunks = find_similar_runbook_chunks(
      db,
      query_embedding,
      query_text,
      limit=limit_runbook,
  )
  ```

  Check whether `logger` is already defined in `incident_summaries.py` — if not, add near the top:
  ```python
  import logging
  logger = logging.getLogger(__name__)
  ```

- [ ] **Step 3.6: Wrap `embed_text` in `runbooks.py`**

  In `backend/app/api/runbooks.py`, change:

  ```python
  query_embedding = embed_text(q, mode="query")
  matches = find_similar_runbook_chunks(db, query_embedding, q, limit=limit)
  ```

  to:

  ```python
  try:
      query_embedding = embed_text(q, mode="query")
  except RuntimeError as exc:
      logger.warning("Embedding unavailable for runbook search, falling back to BM25: %s", exc)
      query_embedding = None
  matches = find_similar_runbook_chunks(db, query_embedding, q, limit=limit)
  ```

  Add logger if not present:
  ```python
  import logging
  logger = logging.getLogger(__name__)
  ```

- [ ] **Step 3.7: Run all unit tests**

  ```bash
  cd /Users/felix/incident-triage
  pytest tests/ -m unit -v
  ```
  Expected: all PASS.

- [ ] **Step 3.8: Commit**

  ```bash
  cd /Users/felix/incident-triage
  git add backend/app/services/incident_summaries.py \
          backend/app/api/runbooks.py \
          tests/backend/unit/test_incident_summaries.py \
          tests/backend/unit/test_incident_similarity.py
  git commit -m "fix: catch embedding RuntimeError in summarize_incident and runbook search, degrade to BM25"
  ```

---

## Post-Implementation Verification

- [ ] Run full unit suite:
  ```bash
  pytest tests/ -m unit -v
  ```

- [ ] Confirm ingestion still hard-fails (no change needed, just verify):
  Read `backend/app/services/ingestion.py` and confirm there is no `try/except` wrapping `embed_texts` inside `upsert_markdown_document`. The call should still propagate `RuntimeError` unmodified.

- [ ] Manual smoke test (with services running):
  Stop the ML service, then trigger an alert webhook. The alert should be processed and grouped into an incident. The incident should have `incident_embedding = NULL` in the DB. Running a `GET /runbooks/search?q=redis` query should return BM25 results rather than a 500.
