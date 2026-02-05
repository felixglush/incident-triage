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

## RAG Implementation Plan
### Retrieval Strategy
- Hybrid retrieval: vector similarity + keyword (BM25) blend.
- Add optional rerank stage (cross-encoder or LLM) for top-k results.
- Enforce minimum relevance thresholds for both vector and keyword signals.

#### Retrieval Config (Env Vars)
- `RAG_VECTOR_WEIGHT` (default `0.7`): weight for vector similarity score.
- `RAG_KEYWORD_WEIGHT` (default `0.3`): weight for keyword overlap score.
- `RAG_MIN_SCORE` (default `0.1`): minimum blended score to keep a match.
- `RAG_MIN_KEYWORD_OVERLAP` (default `0.05`): minimum keyword overlap to keep a match.
- `RAG_RERANK_TITLE_BOOST` (default `0.08`): boost if query appears in title.
- `RAG_RERANK_PHRASE_BOOST` (default `0.05`): boost if query appears in content.

Notes:
- Current implementation uses deterministic token overlap for keyword scoring.
- BM25 can be added later without changing the external API; keep the interface stable.

### Chunking Strategy
- Chunk runbooks by semantic sections (headings/paragraphs).
- Target ~300–800 tokens with 10–20% overlap.
- Preserve `source_document`, `chunk_index`, `tags`, and `title` for citations.

### Indexing + Caching
- Persist runbook chunks with embeddings and metadata for fast reuse.
- Cache recent summaries keyed by incident + runbook version.
- Invalidate cache when runbook content changes.

### Evaluation + Quality
- Track retrieval coverage: which alerts/services are matched to runbooks.
- Add offline eval fixtures for known “gold” runbook matches.
