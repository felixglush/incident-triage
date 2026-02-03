# Phase 3 Requirements — Pairing + Summaries

## Goal
Pair new incidents to prior ones and generate summaries with citations and next steps.

## What Already Exists
- Runbook chunk storage + pgvector extension enablement
- Incident and alert review endpoints
- ML service for classification + entity extraction

## Gaps / What Must Be Added
### 1) Incident Embeddings
- Store `incident_embedding` on each incident (Vector(384) when pgvector is available).
- Update embeddings when alerts are grouped into incidents.

### 2) Similarity Search
- `GET /incidents/{id}/similar` returns top related incidents with scores.
- Uses pgvector distance when available; falls back to token overlap.
- Retrieval implementation should be pluggable to allow later BM25 + vector hybrid.
- Apply a relevance gate to exclude dissimilar incidents:
  - Minimum score threshold (default `min_score=0.1`)
  - Token overlap or shared services must pass basic relevance check

### 3) Summaries + Citations
- `POST /incidents/{id}/summarize` generates a summary with:
  - similar incident references
  - runbook references with citations
- Include alert IDs in citations when alerts are referenced.
- Store `summary_citations` on the incident.

### 4) Next-Step Suggestions
- Generate and store `next_steps` on the incident.
- Use deterministic heuristics (severity, affected services, top similar/runbook).

## Proposed Database Changes
- Extend `Incident` model:
  - `incident_embedding` (Vector(384) or JSONB fallback)
  - `summary_citations` (JSONB)
  - `next_steps` (JSONB)

## Caching Rules
- `POST /incidents/{id}/summarize` returns cached summary/citations/next_steps
  when already present unless `force=true`.

## Confirmed Scope Notes
- Summaries should include retrieved context + citations.
- Next steps are stored on incidents.
- Similarity should be deterministic now, hybrid-ready later (BM25 + vector).
- Similarity gating should prevent unrelated incidents from appearing.

## Swappable Strategy Notes
- `embeddings.py` owns the embedding implementation; `incident_similarity.py` only depends on the interface.
- Future BM25 + vector hybrid retrieval should not change API endpoints or response shapes.
