"""
Unit tests for WebhookProcessor service.

Tests the webhook processing logic in isolation with database fixtures.
"""

from datetime import datetime, timezone

import pytest

from app.models import Alert
from app.services.webhook_processor import WebhookProcessor
from tests.backend.fixtures.factories import AlertFactory, configure_factories
from tests.backend.fixtures.sample_payloads import (
    DATADOG_HIGH_CPU,
    DUPLICATE_ALERT_1,
    DUPLICATE_ALERT_2,
    SENTRY_JAVASCRIPT_ERROR,
)


class TestDatadogWebhookProcessing:
    """Test suite for Datadog webhook processing."""

    @pytest.mark.unit
    @pytest.mark.database
    def test_process_new_datadog_alert(self, db_session):
        """Test processing a new Datadog alert creates database record."""
        processor = WebhookProcessor(db_session)
        payload = DATADOG_HIGH_CPU

        alert = processor.process_datadog_webhook(payload)

        assert alert is not None
        assert alert.id is not None  # Database ID assigned
        assert alert.external_id == payload["id"]
        assert alert.source == "datadog"
        assert alert.title == payload["title"]
        assert alert.message == payload["body"]
        assert alert.raw_payload == payload
        assert alert.severity is None  # Not yet classified
        assert alert.incident_id is None  # Not yet grouped

    @pytest.mark.unit
    @pytest.mark.database
    def test_duplicate_datadog_alert_detection(self, db_session):
        """Test that duplicate alerts are detected by external_id."""
        processor = WebhookProcessor(db_session)

        # Process first occurrence
        alert1 = processor.process_datadog_webhook(DUPLICATE_ALERT_1)
        first_id = alert1.id

        # Process duplicate (same external_id)
        alert2 = processor.process_datadog_webhook(DUPLICATE_ALERT_2)

        # Should return same alert, not create new one
        assert alert2.id == first_id
        assert alert2.external_id == alert1.external_id

        # Verify only one alert in database
        count = db_session.query(Alert).filter(
            Alert.external_id == DUPLICATE_ALERT_1["id"]
        ).count()
        assert count == 1

    @pytest.mark.unit
    @pytest.mark.database
    def test_datadog_timestamp_parsing(self, db_session):
        """Test that Datadog timestamps are correctly parsed."""
        processor = WebhookProcessor(db_session)
        payload = DATADOG_HIGH_CPU.copy()
        payload["last_updated"] = "2024-01-15T10:30:00Z"

        alert = processor.process_datadog_webhook(payload)

        assert alert.alert_timestamp is not None
        assert alert.alert_timestamp.year == 2024
        assert alert.alert_timestamp.month == 1
        assert alert.alert_timestamp.day == 15

    @pytest.mark.unit
    @pytest.mark.database
    def test_datadog_with_missing_fields(self, db_session):
        """Test processing Datadog alert with minimal required fields."""
        processor = WebhookProcessor(db_session)
        minimal_payload = {
            "id": "minimal-001",
            "title": "Minimal alert",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        alert = processor.process_datadog_webhook(minimal_payload)

        assert alert is not None
        assert alert.external_id == "minimal-001"
        assert alert.title == "Minimal alert"
        assert alert.message == ""  # Default to empty string if missing


class TestSentryWebhookProcessing:
    """Test suite for Sentry webhook processing."""

    @pytest.mark.unit
    @pytest.mark.database
    def test_process_new_sentry_alert(self, db_session):
        """Test processing a new Sentry alert."""
        processor = WebhookProcessor(db_session)
        payload = SENTRY_JAVASCRIPT_ERROR

        alert = processor.process_sentry_webhook(payload)

        assert alert is not None
        assert alert.external_id == payload["data"]["issue"]["id"]
        assert alert.source == "sentry"
        assert alert.title == payload["data"]["issue"]["title"]
        assert alert.raw_payload == payload

    @pytest.mark.unit
    @pytest.mark.database
    def test_sentry_duplicate_detection(self, db_session):
        """Test Sentry duplicate detection by issue ID."""
        processor = WebhookProcessor(db_session)

        # Process same Sentry issue twice
        alert1 = processor.process_sentry_webhook(SENTRY_JAVASCRIPT_ERROR)
        alert2 = processor.process_sentry_webhook(SENTRY_JAVASCRIPT_ERROR)

        assert alert1.id == alert2.id
        assert alert1.external_id == alert2.external_id

    @pytest.mark.unit
    @pytest.mark.database
    def test_sentry_timestamp_parsing(self, db_session):
        """Test Sentry lastSeen timestamp parsing."""
        processor = WebhookProcessor(db_session)
        payload = SENTRY_JAVASCRIPT_ERROR.copy()
        payload["data"]["issue"]["lastSeen"] = "2024-01-20T14:30:00.000Z"

        alert = processor.process_sentry_webhook(payload)

        assert alert.alert_timestamp is not None
        assert alert.alert_timestamp.year == 2024


class TestWebhookProcessorEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.unit
    @pytest.mark.database
    def test_concurrent_duplicate_handling(self, db_session):
        """Test handling of concurrent duplicate alerts."""
        configure_factories(db_session)

        # Create an existing alert using factory
        existing = AlertFactory(external_id="concurrent-001", source="datadog")
        db_session.commit()

        # Try to process alert with same external_id
        processor = WebhookProcessor(db_session)
        payload = {
            "id": "concurrent-001",
            "title": "Concurrent test",
            "body": "Testing concurrent processing",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        alert = processor.process_datadog_webhook(payload)

        # Should return existing alert, not create duplicate
        assert alert.id == existing.id

    @pytest.mark.unit
    @pytest.mark.database
    def test_special_characters_in_external_id(self, db_session):
        """Test handling of special characters in external_id."""
        processor = WebhookProcessor(db_session)
        special_id = "alert-123!@#$%^&*()_+-={}[]|:;<>?,./~`"

        payload = {
            "id": special_id,
            "title": "Special ID test",
            "body": "Testing special characters",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        alert = processor.process_datadog_webhook(payload)

        assert alert.external_id == special_id

    @pytest.mark.unit
    @pytest.mark.database
    def test_json_payload_preservation(self, db_session):
        """Test that raw JSONB payload is preserved exactly."""
        processor = WebhookProcessor(db_session)
        payload = DATADOG_HIGH_CPU.copy()
        payload["custom_field"] = {"nested": {"data": [1, 2, 3]}}

        alert = processor.process_datadog_webhook(payload)

        # Verify entire payload is stored
        assert alert.raw_payload == payload
        assert alert.raw_payload["custom_field"]["nested"]["data"] == [1, 2, 3]

    @pytest.mark.unit
    @pytest.mark.database
    def test_unicode_content_handling(self, db_session):
        """Test handling of Unicode characters in alert content."""
        processor = WebhookProcessor(db_session)
        payload = {
            "id": "unicode-001",
            "title": "Alert with émojis 🚀 and special chars ñ é ü",
            "body": "Testing Unicode: 中文 日本語 한국어",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        alert = processor.process_datadog_webhook(payload)

        assert "🚀" in alert.title
        assert "中文" in alert.message
        assert alert.raw_payload["title"] == payload["title"]


class TestWebhookProcessorTransactions:
    """Test database transaction handling."""

    @pytest.mark.unit
    @pytest.mark.database
    def test_rollback_on_error(self, db_session):
        """Test that database session rolls back on errors."""
        processor = WebhookProcessor(db_session)

        # Get initial count
        initial_count = db_session.query(Alert).count()

        # This should fail due to missing required fields
        with pytest.raises(Exception):
            processor.process_datadog_webhook({})  # Invalid payload

        # Count should remain unchanged (rollback occurred)
        final_count = db_session.query(Alert).count()
        assert final_count == initial_count

    @pytest.mark.unit
    @pytest.mark.database
    def test_multiple_alerts_in_session(self, db_session):
        """Test processing multiple alerts in same session."""
        processor = WebhookProcessor(db_session)

        alert1 = processor.process_datadog_webhook(
            {"id": "multi-001", "title": "Alert 1", "last_updated": datetime.now(timezone.utc).isoformat()}
        )
        alert2 = processor.process_datadog_webhook(
            {"id": "multi-002", "title": "Alert 2", "last_updated": datetime.now(timezone.utc).isoformat()}
        )

        assert alert1.id != alert2.id
        assert db_session.query(Alert).count() >= 2
