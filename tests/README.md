# OpsRelay Test Suite

Comprehensive test suite for OpsRelay Phase 1 (Webhooks and Celery Workers).

## Test Organization

```
tests/
├── conftest.py                    # Root fixtures (database, Celery, FastAPI client)
├── backend/
│   ├── conftest.py                # Backend-specific fixtures
│   ├── fixtures/
│   │   ├── factories.py           # Factory Boy factories for test data
│   │   └── sample_payloads.py     # Sample webhook payloads
│   ├── unit/
│   │   ├── test_signature_verification.py
│   │   ├── test_webhook_processor.py
│   │   └── test_celery_tasks.py
│   └── integration/
│       ├── test_webhook_endpoints.py
│       └── test_celery_integration.py
└── pytest.ini                     # Pytest configuration
```

## Setup

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements-dev.txt
```

### 2. Start Test Infrastructure

```bash
# Start test database and Redis
docker-compose -f docker-compose.test.yml up -d

# Wait for services to be healthy
docker-compose -f docker-compose.test.yml ps
```

### 3. Initialize Test Database

```bash
cd backend
python init_db.py --drop  # Optional: drop existing tables first
python init_db.py
```

## Running Tests

### Run All Tests

```bash
cd tests
pytest
```

### Run Specific Test Categories

```bash
# Unit tests only (fast, isolated)
pytest -m unit

# Integration tests only (requires database)
pytest -m integration

# Webhook tests
pytest -m webhook

# Celery tests
pytest -m celery

# Database tests
pytest -m database
```

### Run Specific Test Files

```bash
# Signature verification tests
pytest backend/unit/test_signature_verification.py

# Webhook endpoint tests
pytest backend/integration/test_webhook_endpoints.py

# Celery integration tests
pytest backend/integration/test_celery_integration.py
```

### Run Specific Test Classes or Functions

```bash
# Single test class
pytest backend/unit/test_signature_verification.py::TestDatadogSignatureVerification

# Single test function
pytest backend/unit/test_signature_verification.py::TestDatadogSignatureVerification::test_valid_signature
```

## Test Output Options

### Verbose Output

```bash
pytest -v
```

### Show Print Statements

```bash
pytest -s
```

### Stop on First Failure

```bash
pytest -x
```

### Run Last Failed Tests

```bash
pytest --lf
```

### Show Slowest Tests

```bash
pytest --durations=10
```

## Coverage

### Generate Coverage Report

```bash
# Run tests with coverage
pytest --cov=backend/app --cov-report=html

# View HTML report
open htmlcov/index.html
```

### Coverage Requirements

- Target: 80% code coverage
- Excludes: migrations, init scripts, type checking blocks

## Test Markers

Tests are organized using pytest markers:

- `@pytest.mark.unit` - Unit tests (isolated, fast)
- `@pytest.mark.integration` - Integration tests (database, Redis)
- `@pytest.mark.slow` - Tests taking > 1 second
- `@pytest.mark.webhook` - Webhook-related tests
- `@pytest.mark.celery` - Celery task tests
- `@pytest.mark.database` - Tests requiring database

## Writing New Tests

### Unit Test Example

```python
import pytest
from app.services.webhook_processor import WebhookProcessor

@pytest.mark.unit
@pytest.mark.database
def test_process_datadog_alert(db_session):
    processor = WebhookProcessor(db_session)
    payload = {"id": "test-001", "title": "Test Alert"}

    alert = processor.process_datadog_webhook(payload)

    assert alert.external_id == "test-001"
```

### Integration Test Example

```python
import pytest

@pytest.mark.integration
@pytest.mark.webhook
def test_webhook_endpoint(test_client, db_session):
    response = test_client.post("/webhook/datadog", json={
        "id": "test-001",
        "title": "Test Alert"
    })

    assert response.status_code == 200
    assert response.json()["status"] == "received"
```

### Using Factories

```python
from tests.backend.fixtures.factories import AlertFactory, configure_factories

@pytest.mark.unit
def test_with_factory(db_session):
    configure_factories(db_session)

    alert = AlertFactory(severity="critical")
    assert alert.severity == "critical"
```

## Fixtures

### Database Fixtures

- `db_session` - Function-scoped transactional database session (auto-rollback)
- `setup_test_database` - Session-scoped database table creation

### Celery Fixtures

- `celery_app` - Celery app configured for eager mode (synchronous)
- `celery_config` - Celery configuration dict

### API Fixtures

- `test_client` - FastAPI test client with database override

### Sample Data Fixtures

- `sample_datadog_payload` - Sample Datadog webhook payload
- `sample_sentry_payload` - Sample Sentry webhook payload
- `mock_ml_classification` - Mock ML classification response
- `mock_ml_entities` - Mock entity extraction response

## Troubleshooting

### Database Connection Errors

```bash
# Check test database is running
docker-compose -f docker-compose.test.yml ps postgres-test

# Verify connection
docker-compose -f docker-compose.test.yml exec postgres-test psql -U user -d opsrelay_test -c "SELECT 1;"

# Restart test database
docker-compose -f docker-compose.test.yml restart postgres-test
```

### Test Database Not Clean

```bash
# Drop and recreate test database
docker-compose -f docker-compose.test.yml down -v
docker-compose -f docker-compose.test.yml up -d

# Or reset in Python
cd backend
python init_db.py --drop
python init_db.py
```

### Import Errors

```bash
# Ensure backend is in Python path
export PYTHONPATH="${PYTHONPATH}:${PWD}/backend"

# Or run from tests directory (conftest.py handles path)
cd tests
pytest
```

### Celery Tasks Not Running

In test environment, Celery runs in **eager mode** (synchronous):
- Tasks execute immediately in the same process
- No worker needed
- Easier to test and debug

If you need to test with a real worker:
```bash
# Start test worker
cd backend
celery -A app.workers.celery_app worker --loglevel=info
```

## CI/CD Integration

Tests are configured for GitHub Actions. See `.github/workflows/test.yml`.

## Best Practices

1. **Use Fixtures**: Leverage pytest fixtures for common setup
2. **Use Factories**: Use Factory Boy for test data generation
3. **Mark Tests**: Use markers to organize tests by category
4. **Isolate Tests**: Each test should be independent
5. **Test Edge Cases**: Cover error conditions and boundary cases
6. **Keep Tests Fast**: Use unit tests for business logic, integration tests for flows
7. **Mock External Services**: Mock ML service, external APIs in unit tests

## Performance

Expected test execution times:
- Unit tests: < 10 seconds
- Integration tests: < 30 seconds
- Full suite: < 1 minute

## Additional Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Factory Boy Documentation](https://factoryboy.readthedocs.io/)
- [FastAPI Testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [Celery Testing](https://docs.celeryproject.org/en/stable/userguide/testing.html)
