"""
Root conftest.py for pytest fixtures shared across all tests.

This file provides:
- Hybrid database session (transactional rollback for unit tests, real commits for integration tests)
- Celery app configured for eager mode (synchronous testing)
- FastAPI test client with database override
"""

import os
import sys
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure env vars are set before importing app modules
test_database_url = os.getenv("TEST_DATABASE_URL")
if test_database_url:
    os.environ["DATABASE_URL"] = test_database_url
else:
    os.environ.setdefault(
        "DATABASE_URL", "postgresql://user:password@localhost:54323/opsrelay_test"
    )
os.environ.setdefault("REDIS_URL", "redis://localhost:6380/0")
os.environ.setdefault("SKIP_SIGNATURE_VERIFICATION", "true")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
os.environ.setdefault("CELERY_TASK_EAGER_PROPAGATES", "true")
os.environ.setdefault("TESTING", "true")

# Add backend directory to Python path so we can import app modules
backend_path = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, backend_path)

from app.database import Base, get_db
from app.main import app


# Test Database Configuration
TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://user:password@localhost:54323/opsrelay_test"
)

# Create test engine with connection pooling for isolation
engine = create_engine(
    TEST_DATABASE_URL,
    poolclass=StaticPool,  # Use static pool for testing (single connection)
)

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session")
def setup_test_database():
    """
    Session-scoped fixture to create all database tables once per test session.
    Tables are dropped and recreated at the start of each test session.
    """
    # Drop all tables and recreate (clean slate)
    Base.metadata.drop_all(bind=engine)
    # Ensure required PostgreSQL extensions exist
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    yield
    # Teardown: Drop all tables after test session
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(request, setup_test_database) -> Generator[Session, None, None]:
    """
    Hybrid database session fixture that adapts based on test type.

    - Unit tests: Transactional rollback (fast, isolated, no real commits)
    - Integration tests: Real commits with cleanup (tests actual behavior)

    Integration tests are detected by @pytest.mark.integration marker.
    This allows integration tests with Celery to work correctly since Celery
    tasks create their own database sessions and need to see committed data.

    Usage:
        @pytest.mark.unit
        def test_unit(db_session):
            # Fast test with automatic rollback

        @pytest.mark.integration
        def test_integration(db_session):
            # Real commits, cleanup after test
    """
    # Check if this is an integration or celery test (both need real commits)
    is_integration = 'integration' in request.keywords or 'celery' in request.keywords

    if is_integration:
        # Integration test: Use real commits with cleanup
        session = TestingSessionLocal()

        yield session

        # Clean up all test data in reverse dependency order
        from app.models import IncidentAction, Alert, Incident, RunbookChunk

        session.query(IncidentAction).delete()
        session.query(Alert).delete()
        session.query(Incident).delete()
        session.query(RunbookChunk).delete()
        session.commit()
        session.close()
    else:
        # Unit test: Use transactional rollback (fast, isolated)
        connection = engine.connect()
        transaction = connection.begin()
        session = TestingSessionLocal(bind=connection)

        yield session

        # Rollback transaction (undo all changes from test)
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="function")
def test_client(db_session) -> TestClient:
    """
    FastAPI test client with database session override.

    This ensures API endpoints use the transactional test database session
    instead of the production database.

    Usage:
        def test_webhook_endpoint(test_client):
            response = test_client.post("/webhook/datadog", json={...})
            assert response.status_code == 200
    """

    def override_get_db():
        try:
            yield db_session
        finally:
            db_session.expire_all()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        yield client

    # Clean up dependency override
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def celery_config():
    """
    Celery configuration for testing with eager mode.

    Eager mode runs tasks synchronously (no worker needed), making tests faster
    and more predictable. Tasks execute in the same process as the test.
    """
    return {
        "broker_url": "memory://",
        "result_backend": "cache+memory://",
        "task_always_eager": True,
        "task_eager_propagates": True,
    }


@pytest.fixture(scope="function")
def celery_app(celery_config):
    """
    Celery app configured for eager mode (synchronous) testing.

    Usage:
        def test_celery_task(celery_app):
            from app.workers.tasks import process_alert
            result = process_alert.delay(alert_id=1)
            assert result.successful()
    """
    from app.workers.celery_app import celery_app as app

    app.conf.update(celery_config)
    return app


# Pytest markers for organizing tests
def pytest_configure(config):
    """Register custom markers for test organization."""
    config.addinivalue_line("markers", "unit: Unit tests (isolated, fast)")
    config.addinivalue_line("markers", "integration: Integration tests (database, Redis)")
    config.addinivalue_line("markers", "slow: Tests that take more than 1 second")
    config.addinivalue_line("markers", "webhook: Webhook endpoint tests")
    config.addinivalue_line("markers", "celery: Celery task tests")
