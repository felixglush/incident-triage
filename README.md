# incident-triage (OpsRelay)

OpsRelay is an AI-powered incident management system that ingests alerts,
groups them into incidents, and assists on-call engineers with summaries and
recommended next steps.

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

## Development Notes
- Webhook processing is async; classification defaults safely on failure.
- Use `SKIP_SIGNATURE_VERIFICATION=true` only in development.
