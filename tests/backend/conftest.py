"""
Backend-specific pytest fixtures.

Provides fixtures for:
- Database models (Alert, Incident, etc.)
- Sample webhook payloads
- Mock ML service responses
"""

from datetime import datetime, timezone

import pytest


@pytest.fixture
def sample_datadog_payload():
    """Sample Datadog webhook payload for testing."""
    return {
        "id": "test-datadog-001",
        "title": "High CPU usage on api-service",
        "body": "CPU utilization exceeded 80% for 5 minutes",
        "priority": "warning",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "tags": ["service:api-service", "env:production", "region:us-east-1"],
    }


@pytest.fixture
def sample_sentry_payload():
    """Sample Sentry webhook payload for testing."""
    return {
        "id": "test-sentry-001",
        "data": {
            "issue": {
                "id": "test-sentry-001",
                "title": "TypeError: Cannot read property 'x' of undefined",
                "lastSeen": datetime.now(timezone.utc).isoformat(),
            }
        },
        "action": "created",
    }


@pytest.fixture
def mock_ml_classification():
    """Mock ML classification response."""
    return {
        "severity": "warning",
        "predicted_team": "backend",
        "confidence_score": 0.85,
    }


@pytest.fixture
def mock_ml_entities():
    """Mock ML entity extraction response."""
    return {
        "service_name": "api-service",
        "environment": "production",
        "region": "us-east-1",
        "error_code": None,
    }
