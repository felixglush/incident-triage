# incident-triage (OpsRelay)

OpsRelay is an AI-powered incident management system that ingests alerts,
groups them into incidents, and assists on-call engineers with summaries and
recommended next steps.

## Status
See `implementation.md` and `ROADMAP.md` for the phased plan.

## Dev Quickstart

// To add

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
