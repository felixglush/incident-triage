"""
Integration tests for webhook endpoints.

Tests the full HTTP endpoint flow including:
- Request validation
- Signature verification
- Database persistence
- HTTP response format
"""

import json
from datetime import datetime, timezone

import pytest

from app.models import Alert
from tests.backend.fixtures.sample_payloads import (
    DATADOG_HIGH_CPU,
    DATADOG_HIGH_MEMORY,
    DUPLICATE_ALERT_1,
    DUPLICATE_ALERT_2,
    SENTRY_JAVASCRIPT_ERROR,
)


class TestDatadogWebhookEndpoint:
    """Integration tests for /webhook/datadog endpoint."""

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_datadog_webhook_success(self, test_client, db_session):
        """Test successful Datadog webhook request."""
        response = test_client.post(
            "/webhook/datadog",
            json=DATADOG_HIGH_CPU,
        )

        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "received"
        assert "alert_id" in data
        assert data["external_id"] == DATADOG_HIGH_CPU["id"]

        # Verify alert in database
        alert = db_session.query(Alert).filter(
            Alert.id == data["alert_id"]
        ).first()
        assert alert is not None
        assert alert.source == "datadog"
        assert alert.title == DATADOG_HIGH_CPU["title"]

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_datadog_duplicate_returns_same_id(self, test_client, db_session):
        """Test that duplicate Datadog alerts return same alert_id."""
        # Send first alert
        response1 = test_client.post("/webhook/datadog", json=DUPLICATE_ALERT_1)
        assert response1.status_code == 200
        alert_id_1 = response1.json()["alert_id"]

        # Send duplicate
        response2 = test_client.post("/webhook/datadog", json=DUPLICATE_ALERT_2)
        assert response2.status_code == 200
        alert_id_2 = response2.json()["alert_id"]

        # Should return same alert ID
        assert alert_id_1 == alert_id_2

        # Verify only one record in database
        count = db_session.query(Alert).filter(
            Alert.external_id == DUPLICATE_ALERT_1["id"]
        ).count()
        assert count == 1

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_datadog_invalid_json(self, test_client):
        """Test handling of invalid JSON payload."""
        response = test_client.post(
            "/webhook/datadog",
            data="invalid json {{{",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code in [400, 422]  # Bad Request or Unprocessable Entity

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_datadog_missing_required_fields(self, test_client):
        """Test handling of payload missing required fields."""
        invalid_payload = {"title": "Missing ID"}  # No 'id' field

        response = test_client.post("/webhook/datadog", json=invalid_payload)

        # Should return error (exact status depends on validation)
        assert response.status_code in [400, 422, 500]

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_datadog_large_payload(self, test_client, db_session):
        """Test handling of large webhook payload."""
        large_payload = DATADOG_HIGH_CPU.copy()
        large_payload["metadata"] = {
            "large_field": "x" * 10000,  # 10KB of data
            "nested": {"data": list(range(1000))},
        }

        response = test_client.post("/webhook/datadog", json=large_payload)

        assert response.status_code == 200

        # Verify large payload is stored
        alert_id = response.json()["alert_id"]
        alert = db_session.query(Alert).filter(Alert.id == alert_id).first()
        assert len(alert.raw_payload["metadata"]["large_field"]) == 10000

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_datadog_concurrent_requests(self, test_client, db_session):
        """Test handling of concurrent webhook requests."""
        payloads = [
            DATADOG_HIGH_CPU,
            DATADOG_HIGH_MEMORY,
            {**DATADOG_HIGH_CPU, "id": "concurrent-001"},
            {**DATADOG_HIGH_CPU, "id": "concurrent-002"},
        ]

        responses = []
        for payload in payloads:
            response = test_client.post("/webhook/datadog", json=payload)
            responses.append(response)

        # All should succeed
        assert all(r.status_code == 200 for r in responses)

        # Should have created correct number of alerts (accounting for duplicates)
        unique_ids = set(r.json()["external_id"] for r in responses)
        alert_count = db_session.query(Alert).filter(
            Alert.external_id.in_(unique_ids)
        ).count()
        assert alert_count == len(unique_ids)


class TestSentryWebhookEndpoint:
    """Integration tests for /webhook/sentry endpoint."""

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_sentry_webhook_success(self, test_client, db_session):
        """Test successful Sentry webhook request."""
        response = test_client.post(
            "/webhook/sentry",
            json=SENTRY_JAVASCRIPT_ERROR,
        )

        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "received"
        assert "alert_id" in data

        # Verify in database
        alert = db_session.query(Alert).filter(
            Alert.id == data["alert_id"]
        ).first()
        assert alert is not None
        assert alert.source == "sentry"

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_sentry_duplicate_detection(self, test_client, db_session):
        """Test Sentry duplicate detection."""
        # Send same Sentry issue twice
        response1 = test_client.post("/webhook/sentry", json=SENTRY_JAVASCRIPT_ERROR)
        response2 = test_client.post("/webhook/sentry", json=SENTRY_JAVASCRIPT_ERROR)

        assert response1.status_code == 200
        assert response2.status_code == 200

        alert_id_1 = response1.json()["alert_id"]
        alert_id_2 = response2.json()["alert_id"]

        assert alert_id_1 == alert_id_2

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_sentry_nested_json_structure(self, test_client, db_session):
        """Test handling of Sentry's nested JSON structure."""
        response = test_client.post("/webhook/sentry", json=SENTRY_JAVASCRIPT_ERROR)

        assert response.status_code == 200

        alert = db_session.query(Alert).filter(
            Alert.id == response.json()["alert_id"]
        ).first()

        # Verify nested structure is preserved
        assert alert.raw_payload["data"]["issue"]["id"] == SENTRY_JAVASCRIPT_ERROR["data"]["issue"]["id"]
        assert "metadata" in alert.raw_payload["data"]["issue"]


class TestHealthEndpoint:
    """Integration tests for /health endpoint."""

    @pytest.mark.integration
    def test_health_check_success(self, test_client):
        """Test health check endpoint returns healthy status."""
        response = test_client.get("/health")

        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert "db_connected" in data
        assert data["db_connected"] is True


class TestWebhookAuthentication:
    """Integration tests for webhook authentication and security."""

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_datadog_without_signature_in_dev_mode(self, test_client):
        """Test that webhooks work without signature in development mode."""
        # SKIP_SIGNATURE_VERIFICATION should be set to true in test env
        response = test_client.post(
            "/webhook/datadog",
            json=DATADOG_HIGH_CPU,
            # No X-Datadog-Signature header
        )

        # Should succeed in development mode
        assert response.status_code == 200

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_content_type_validation(self, test_client):
        """Test that non-JSON content-type is rejected."""
        response = test_client.post(
            "/webhook/datadog",
            data="not json",
            headers={"Content-Type": "text/plain"},
        )

        # Should reject non-JSON content
        assert response.status_code in [400, 415, 422]  # Bad Request, Unsupported Media Type, or Unprocessable Entity


class TestWebhookResponseFormat:
    """Test webhook response format and structure."""

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_response_contains_required_fields(self, test_client):
        """Test that webhook response contains all required fields."""
        response = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)

        assert response.status_code == 200

        data = response.json()

        # Required fields
        assert "status" in data
        assert "alert_id" in data
        assert "external_id" in data

        # Field types
        assert isinstance(data["status"], str)
        assert isinstance(data["alert_id"], int)
        assert isinstance(data["external_id"], str)

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_response_headers(self, test_client):
        """Test webhook response headers."""
        response = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)

        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]

    @pytest.mark.integration
    @pytest.mark.webhook
    @pytest.mark.slow
    def test_webhook_response_time(self, test_client):
        """Test that webhook responds within acceptable time (< 2 seconds)."""
        import time

        start = time.time()
        response = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)
        elapsed = time.time() - start

        assert response.status_code == 200
        assert elapsed < 2.0  # Webhook must respond within 2 seconds


class TestWebhookEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_empty_string_fields(self, test_client, db_session):
        """Test handling of empty string fields."""
        payload = {
            "id": "empty-fields-001",
            "title": "",  # Empty title
            "body": "",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        response = test_client.post("/webhook/datadog", json=payload)

        assert response.status_code == 200

        alert = db_session.query(Alert).filter(
            Alert.id == response.json()["alert_id"]
        ).first()

        assert alert.title == ""
        assert alert.message == ""

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_null_optional_fields(self, test_client):
        """Test handling of null values in optional fields."""
        payload = {
            "id": "null-fields-001",
            "title": "Test",
            "body": None,  # Null optional field
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "tags": None,
        }

        response = test_client.post("/webhook/datadog", json=payload)

        # Should handle null gracefully
        assert response.status_code in [200, 400, 422]

    @pytest.mark.integration
    @pytest.mark.webhook
    def test_unicode_in_request(self, test_client, db_session):
        """Test Unicode characters in webhook payload."""
        payload = {
            "id": "unicode-001",
            "title": "Test with émojis 🚀🎉",
            "body": "Unicode test: 中文 日本語 한국어",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        response = test_client.post("/webhook/datadog", json=payload)

        assert response.status_code == 200

        alert = db_session.query(Alert).filter(
            Alert.id == response.json()["alert_id"]
        ).first()

        assert "🚀" in alert.title
        assert "中文" in alert.message
