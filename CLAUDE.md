# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

When exiting plan mode to begin implementation, ALWAYS save the implementation plan first as a markdown file in `docs/`.

## Commands

### Start all services
```bash
docker-compose up --build
```
Ports: Frontend `3001`, Backend API `8000`, ML service `8001`, Postgres `54322`, Redis `6379`.

### Run tests (from project root)
```bash
pytest tests/
```

```bash
# Unit tests only (fast, no DB/Redis needed)
pytest tests/ -m unit

# Integration tests (requires Postgres + Redis)
docker-compose -f docker-compose.test.yml up -d
pytest tests/ -m integration

# Single test file
pytest tests/backend/unit/test_signature_verification.py

# Single test
pytest tests/backend/unit/test_signature_verification.py::test_name
```

Integration tests use a separate DB on port `54323` and Redis on port `6380` (from `docker-compose.test.yml`).

### Database initialization
Run once after starting Postgres, or to reset schema:
```bash
cd backend
python init_db.py           # schema only
python init_db.py --seed    # schema + seed data
python init_db.py --drop --yes  # WARNING: drops and recreates
```

### Frontend dev (outside Docker)
```bash
cd frontend && npm install && npm run dev   # port 3000
```
Set `OPSRELAY_API_BASE_URL=http://localhost:8000` in the environment when running the frontend outside Docker.

### Load sample data / generate embeddings
```bash
python datasets/load_sample_data.py
python datasets/generate_alerts.py
python datasets/generate_runbooks.py
```

### RAG evals
```bash
cd backend
python tools/run_rag_eval.py --dataset ../datasets/evals/rag_eval_cases.jsonl --limit 5
```

## Architecture

OpsRelay is a multi-service AI-powered incident management system. Five Docker services cooperate:

| Service | Description |
|---|---|
| `backend` | FastAPI API + Celery workers (Python) |
| `ml-service` | Separate FastAPI service for ML inference (DistilBERT, BERT, sentence-transformers) |
| `celery-worker` | Same image as `backend`, runs `celery -A app.workers.celery_app worker` |
| `postgres` | PostgreSQL 18 with pgvector and pg_trgm extensions |
| `frontend` | Next.js 14, proxies all API calls to `backend` |

### Alert → Incident pipeline

1. Monitoring platforms POST to `POST /webhook/{platform}` (Datadog, Sentry).
2. `backend/app/api/webhooks.py` validates signatures, deduplicates via `(source, external_id)`, stores alert in DB, then enqueues `process_alert.delay(alert_id)` and returns immediately.
3. The Celery worker (`backend/app/workers/tasks.py`) calls the ML service for classification (severity, team) and entity extraction (service, env, region), then runs grouping logic to assign the alert to an existing or new Incident.
4. When an incident accumulates enough alerts (or on-demand), `incident_summaries.py` calls Claude to generate a summary, next steps, and RAG citations using hybrid search.

### RAG / hybrid search

`backend/app/services/ingestion.py` chunks documents and embeds them (sentence-transformers `all-MiniLM-L6-v2`, 384-dim) into the `runbook_chunks` table with pgvector.

Retrieval (`incident_summaries.py`, `chat_orchestrator.py`) blends:
- Vector search: `1 / (1 + l2_distance)` weighted by `RAG_VECTOR_WEIGHT` (default 0.7)
- BM25 via PostgreSQL `ts_rank_cd` weighted by `RAG_KEYWORD_WEIGHT` (default 0.3)
- Reranker boost for title/content phrase matches

### Chat streaming

`POST /chat/{incident_id}/stream` returns a streaming response (SSE). The frontend reads it via the `EventSource`/`fetch` streaming pattern. `backend/app/api/chat.py` → `chat_orchestrator.py` → `incident_summaries.py` (which calls Claude with `stream=True`).

### Frontend API proxy

All browser API calls use **relative URLs** to `/api/opsrelay/...`. Next.js Route Handlers in `frontend/app/api/opsrelay/` forward requests to the backend using `OPSRELAY_API_BASE_URL` (set to `http://backend:8000` in Docker). Never set `NEXT_PUBLIC_API_BASE_URL` — that would bypass the proxy. The shared helper is `frontend/app/api/opsrelay/_base.ts`.

### Notion connector

`backend/app/services/notion_connector.py` crawls a configured root page subtree, converts blocks to Markdown, and upserts via `ingestion.py` into `source_documents` + `runbook_chunks`. The connector state lives in the `connectors` table. Sync is triggered manually via `POST /connectors/notion/sync`; there are no Notion webhooks in v1. Requires `NOTION_TOKEN` and `NOTION_API_VERSION` env vars.

## Database schema

Six SQLAlchemy models in `backend/app/models/database.py`:

- **Alert** — raw webhook payload (`raw_payload` JSONB), ML outputs, extracted entities. Unique on `(source, external_id)`.
- **Incident** — groups alerts, holds `summary`, `next_steps`, `summary_citations` (JSONB), `incident_embedding` (Vector 384).
- **IncidentAction** — immutable audit log; CASCADE-deleted with its incident.
- **RunbookChunk** — document segments for RAG with `embedding` (Vector 384) and `search_tsv` (TSVECTOR) for hybrid search.
- **SourceDocument** — canonical pre-chunked content keyed by `(source_document, source)`; stable layer before re-chunking.
- **Connector** — third-party integration config/status (e.g., Notion). PK is a string slug (e.g., `"notion"`).

No migration tool — schema is managed by `init_db.py` / SQLAlchemy `create_all`.

## Testing patterns

- Tests live in `tests/`; backend code is imported by inserting `backend/` onto `sys.path` in `conftest.py`.
- `db_session` fixture is hybrid: unit tests use transactional rollback; integration/celery tests commit and then clean up.
- Celery tasks run in eager mode (`CELERY_TASK_ALWAYS_EAGER=true`) — no worker process needed.
- ML service is mocked in tests; the transformers pipeline is not loaded.

## Frontend design system

Defined fully in `frontend/CLAUDE.md`. Key rules:
- **No rounded corners** on containers (avoid `rounded-*`).
- Sharp, data-dense, Linear-inspired aesthetic.
- Color tokens: `graphite`, `mist`, `slate`, `critical`, `warning`, `info`, `success`, `accent` (yellow).
- Use `DataTable` component for all tabular data; `AppShell` for page layout.
- Chat panel is 420px wide, right-edge, hidden below `xl` breakpoint.

## Key environment variables

| Var | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `ML_SERVICE_URL` | ML inference service URL |
| `ANTHROPIC_API_KEY` | Required for summaries and chat |
| `OPENAI_API_KEY` | Required for RAG evals (judge model) |
| `NOTION_TOKEN` | Required for Notion connector |
| `NOTION_API_VERSION` | Defaults to `2026-03-11` |
| `SKIP_SIGNATURE_VERIFICATION` | Set `true` in dev to bypass webhook HMAC checks |
| `RAG_VECTOR_WEIGHT` / `RAG_KEYWORD_WEIGHT` | Hybrid search blending weights |
