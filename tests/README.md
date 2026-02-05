# OpsRelay Test Suite

Test suite for OpsRelay backend and ML service.

## Test Organization
```
tests/
├── conftest.py                    # Root fixtures (db, Celery, FastAPI client)
├── backend/
│   ├── conftest.py                # Backend-specific fixtures
│   ├── fixtures/
│   │   ├── factories.py           # Factory Boy factories
│   │   └── sample_payloads.py     # Sample webhook payloads
│   ├── unit/
│   │   ├── test_signature_verification.py
│   │   ├── test_webhook_processor.py
│   │   └── test_celery_tasks.py
│   └── integration/
│       ├── test_webhook_endpoints.py
│       ├── test_celery_integration.py
│       └── test_ml_integration.py
└── ml/
    └── test_inference_service.py
```

## Setup
```bash
cd backend
pip install -r requirements.txt
pip install -r ../requirements-dev.txt
```

## Running Tests
```bash
cd tests
pytest
```

### Common Targets
```bash
# Unit tests only
pytest -m unit

# Integration tests only (requires db/redis)
pytest -m integration

# Webhook tests
pytest -m webhook

# Celery tests
pytest -m celery
```

## Markers
- `unit`: Isolated unit tests
- `integration`: Database/redis integration tests
- `webhook`: Webhook ingestion tests
- `celery`: Celery task tests
- `database`: Tests requiring database

## Notes
- Integration tests require Postgres + Redis (use `docker-compose.test.yml`).
- ML service tests mock the transformers pipeline.
- There is no CI configured yet; tests are run locally.
