# Phase 2 Requirements — Classification + Entity Extraction

## Goal
Classify alerts and extract key entities with clear provenance and confidence.

## What Already Exists
- Rule-based classification + regex/NER extraction in ML service: `ml/inference_server.py`
- Celery task calling ML service: `backend/app/workers/tasks.py`
- Alert model fields: `severity`, `predicted_team`, `confidence_score`, `service_name`, `environment`, `region`, `error_code`

## Gaps / What Must Be Added
### 1) Provenance for Classification + Entities
Add fields to track where results came from:
- **Alert**:
  - `classification_source` (e.g. `rule`, `fallback_rule`)
  - `entity_source` (e.g. `regex`, `ner`, `tags`)

### 2) Entity Pipeline Improvements
- Prefer regex/heuristics first, then NER fallback.
- Persist which path was used in `entity_source`.
- If ML extraction is empty or partial, fill missing entities from alert tags/title.

### 3) Confidence Handling
- Preserve ML confidence when available
- Set explicit fallback confidence when ML service unavailable

### 4) Tests + Fixtures
- Add fixtures for expected entities
- Add unit/integration tests for provenance fields

## Proposed Database Changes
- Extend `Alert` model + migration/init to include:
  - `classification_source` (string, indexed)
  - `entity_source` (string, indexed)

## Confirmed Scope Notes
- Provenance fields live on `Alert` only (for now)
- Use specific source values
- Return provenance in API responses now
- Fallback is tags/title only (no additional heuristics)
