# incident-triage

OpsRelay is an AI-powered incident management system that ingests alerts,
groups them into incidents, and assists on-call engineers with summaries and
recommended next steps.

## Who it's for
Primary persona: on-call engineers and incident responders managing active production issues.

## What it does
- Receives Datadog and Sentry webhooks, verifies signatures, and stores alert payloads.
- Queues asynchronous alert processing with Celery so webhook endpoints return quickly.
- Classifies alerts and extracts entities through an ML service (with graceful fallbacks).
- Groups alerts into incidents and exposes incident, alert, dashboard, and connector APIs.
- Indexes runbook content into chunks and supports runbook search plus retrieval.
- Finds similar incidents/runbook chunks using a hybrid vector + keyword ranking approach.
- Streams incident-scoped assistant responses over SSE with citations for grounding.

## How it works
- Sources: monitoring platforms (Datadog/Sentry) send events to FastAPI webhook routes.
- Backend: FastAPI persists alerts/incidents in PostgreSQL (pgvector) and publishes Celery jobs via Redis.
- ML path: worker calls ML service for classification/entity extraction, then updates alert/incident records.
- Retrieval path: runbook chunks + incident embeddings are queried and reranked for context.
- UX path: Next.js frontend calls backend endpoints; chat endpoint streams assistant deltas/events to UI.

## How to run 
- From repo root: `docker-compose up --build`.
- Open UI/API: frontend <http://localhost:3001>, backend <http://localhost:8000>, ML service <http://localhost:8001>.
- For LLM-backed flows: set `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` in environment/.env.
- If database schema is missing on first run: run `python backend/init_db.py --seed`.


## Status
See `implementation.md` and `ROADMAP.md` for the phased plan.

## Dev Quickstart

### Start the App (Docker Compose)

```bash
docker-compose up --build
```

Services:
- Frontend: http://localhost:3001
- Backend API: http://localhost:8000
- ML service: http://localhost:8001
- Postgres: localhost:54322
- Redis: localhost:6379

Notes:
- `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are optional for basic flows, but required
  for LLM-backed summaries/classification.
- `NOTION_TOKEN` is required for the Notion connector.
- `NOTION_API_VERSION` defaults to `2026-03-11` if not set.
- `SKIP_SIGNATURE_VERIFICATION` is set to `true` in `docker-compose.yml` for local dev.

### Run Tests

Quick run:
```bash
cd tests
pytest
```

Integration tests (requires Postgres + Redis):
```bash
docker-compose -f docker-compose.test.yml up -d
cd tests
pytest -m integration
```

More commands and troubleshooting: see `tests/README.md`.

## Repo Layout
- `backend/`: FastAPI API, Celery workers, DB models
- `ml/`: ML inference service
- `datasets/`: Sample data generators and loaders
- `tests/`: Backend + ML tests
- `docs/`: Architecture and supporting documentation

## Documentation

### Operational Runbooks

Comprehensive on-call runbooks and incident documentation are stored in `datasets/notion_mock/` and synced to the Notion connector for RAG retrieval.

**6 Service Runbooks** (~8,000 lines, ~45,000 words):
- Checkout & Payments (1,573 lines, 1,266 Notion blocks)
- Product Catalog (1,922 lines, 1,531 Notion blocks)
- CDN & Storefront (1,303 lines, 1,022 Notion blocks)
- Auth & Sessions (1,392 lines, 1,097 Notion blocks)
- Queue & Workers (988 lines, 744 Notion blocks)
- Database & Cache (857 lines, 667 Notion blocks)

Each runbook includes:
- Service overview and architecture
- 7 recorded incidents with timeline, root cause, and resolution steps
- Failure mode catalog with diagnosis and remediation
- Runbook procedures (deployment, failover, scaling, rollback)
- Monitoring & alerts with thresholds
- Inter-service impact maps showing cascade effects
- Rollback decision trees for go/no-go choices
- Escalation policy and communication templates

**18 Postmortems** (~1,600 lines, ~9,000 words, 1 per original incident):
- Executive summary, timeline, root cause analysis (5 Whys)
- Contributing factors, remediation, action items
- Lessons learned and follow-up recommendations

**6 Pre-Action Checklists** (~750 lines, ~5,600 words):
- Pre-deploy, pre-sale, pre-maintenance workflows
- Service-specific verification steps and quick-start commands

**Total operational documentation: ~10,400 lines, ~59,600 words** (equivalent to a 180-page technical manual).

All documents are pushed to Notion and synced via the Notion connector for RAG-powered incident assistance.

### Project Documentation
- `implementation.md`: Delivery phases and goals
- `ROADMAP.md`: Milestones and exit criteria
- `docs/architecture.md`: Architecture and data flow

## Development Notes
- Webhook processing is async; classification defaults safely on failure.
- Use `SKIP_SIGNATURE_VERIFICATION=true` only in development.

## Notion Connector Setup
1. Create a Notion **internal integration** in the workspace you want to sync.
2. Grant it read-oriented access for page content.
3. Share one or more designated root page subtrees (for example `OpsRelay Knowledge`, `Runbooks`, `Postmortems`) with the integration.
4. Add the token to `/Users/felix/incident-triage/.env`:

```env
NOTION_TOKEN=secret_xxx
NOTION_API_VERSION=2026-03-11
```

5. Open `http://localhost:3001/connectors`, paste one Notion root page URL or ID per line into the Notion card, then click `Save Root Pages`.
6. Click `Sync Now` to ingest the shared subtree into the local knowledge index.

Notes:
- The connector syncs one or more configured **root page subtrees**, not the entire workspace.
- Synced Notion content is stored locally and retrieved through the existing hybrid search path.
- Notion webhooks are not part of v1; manual sync is the default refresh path for now.
