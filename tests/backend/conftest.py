"""
Backend-specific pytest fixtures.

Provides fixtures for:
- Database models (Alert, Incident, etc.)
- Sample webhook payloads
- Mock ML service responses
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def patch_embed_text(request):
    """
    Auto-patch embed_text/embed_texts for unit tests so they don't call the ML service.
    Integration tests are excluded — they manage their own DB state and may need
    real (or explicitly mocked) embeddings.

    embed_texts uses a side_effect so it scales with input size — returning
    [fake_vec] * len(texts) regardless of batch count. This prevents mismatched
    zip() calls when upsert_markdown_document embeds multiple chunks at once.
    """
    if "unit" not in request.keywords:
        yield
        return
    # Tests marked no_embed_patch manage their own patching (e.g. test_embeddings.py)
    # and must call through to the real embed_text/embed_texts functions.
    if "no_embed_patch" in request.keywords:
        yield
        return
    fake_vec = [0.1] * 1024

    def _fake_embed_texts(texts, mode="document"):
        return [fake_vec for _ in texts]

    with patch("app.services.embeddings.embed_texts", side_effect=_fake_embed_texts) as _mock, \
         patch("app.services.embeddings.embed_text", return_value=fake_vec), \
         patch("app.services.ingestion.embed_texts", side_effect=_fake_embed_texts), \
         patch("app.services.incident_similarity.embed_texts", side_effect=_fake_embed_texts):
        yield _mock


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
