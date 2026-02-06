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
- `implementation.md`: Delivery phases and goals
- `ROADMAP.md`: Milestones and exit criteria
- `docs/architecture.md`: Architecture and data flow
