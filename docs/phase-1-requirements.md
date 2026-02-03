# Phase 1 Requirements — Incident Review + Webhooks

## Goal
Enable reliable ingestion of new alerts via webhooks and provide a first-class
API for reviewing past incidents (list/detail/status) with filters and
pagination.

## What Already Exists
- Webhook endpoints for Datadog/Sentry: `backend/app/api/webhooks.py`
- Signature verification service: `backend/app/services/signature_verification.py`
- Webhook processing + dedupe: `backend/app/services/webhook_processor.py`
- Celery worker for classification + grouping: `backend/app/workers/tasks.py`
- DB models for alerts/incidents/actions: `backend/app/models/database.py`
- Database session/initialization: `backend/app/database.py`
- Webhook and Celery integration tests:
  - `tests/backend/integration/test_webhook_endpoints.py`
  - `tests/backend/integration/test_celery_integration.py`
  - `tests/backend/integration/test_ml_integration.py`
- Sample alert generation + loader: `datasets/generate_alerts.py`, `datasets/load_sample_data.py`

## Gaps / What Must Be Added
### 1) Incidents API (Review Past Incidents)
Add `backend/app/api/incidents.py` and wire in `backend/app/main.py`.

Required endpoints (Phase 1):
- `GET /incidents`
  - Query params: `status`, `severity`, `service`, `team`, `source`,
    `created_from`, `created_to`, `updated_from`, `updated_to`
  - Pagination: `limit`, `offset`
  - Sort: `created_at` desc default
  - Include aggregates: `alert_count`, `last_alert_at`
- `GET /incidents/{id}`
  - Include related alerts and recent actions
- `PATCH /incidents/{id}/status`
  - Enforce status transitions (OPEN -> INVESTIGATING -> RESOLVED -> CLOSED)
  - Record status change in `incident_actions`

Notes:
- The current `backend/app/main.py` has stub `/incidents` returning empty.
  Replace stubs with real router.

### 2) Alerts API (Support Incident Review)
Add `backend/app/api/alerts.py` (or include in incidents router).

Required endpoints (Phase 1):
- `GET /alerts`
  - Query params: `source`, `severity`, `service`, `environment`,
    `created_from`, `created_to`, `incident_id`
  - Pagination: `limit`, `offset`

### 3) Filtering + Pagination Service Layer
Create query helpers to keep filtering logic centralized.
Suggested location: `backend/app/services/incident_query.py`

Requirements:
- Validate params and apply optional filters
- Return total count + paginated results
- Default ordering by `created_at DESC`

### 4) Update Tests
Extend integration tests to cover new endpoints:
- `GET /incidents` returns newly grouped incidents
- `GET /incidents/{id}` returns alerts + actions
- `PATCH /incidents/{id}/status` updates status + creates action
- `GET /alerts` supports filters and pagination

### 5) Seed Data for Review Flows
Extend data scripts to support incident review without manual setup:
- Option A: Use existing `datasets/load_sample_data.py` to ingest alerts
  and rely on Celery grouping to create incidents.
- Option B: Add `datasets/generate_incidents.py` to create incidents + alerts
  directly for deterministic UI demos.

## Acceptance Criteria
- Incidents can be listed, filtered, and paginated via API
- Incident detail includes alerts + actions
- Status changes are validated and logged
- Alerts can be listed and filtered via API
- Integration tests cover core flows
- Seed data produces at least 10 incidents for demo review

## Open Questions to Confirm
- Confirmed:
  - Include aggregates on incident list (`alert_count`, `last_alert_at`)
  - Offset-based pagination
  - Return alerts on incident detail only
