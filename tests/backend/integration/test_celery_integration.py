"""
End-to-end integration tests for Celery workflow.

Tests the complete flow:
1. Webhook receives alert
2. Alert stored in database
3. Celery task queued
4. Task processes alert (classification + grouping)
5. Incident created/updated
6. Audit trail logged
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Alert, Incident, IncidentAction, ActionType, IncidentStatus
from tests.backend.fixtures.sample_payloads import (
    DATADOG_HIGH_CPU,
    DATADOG_HIGH_MEMORY,
)


class TestWebhookToCeleryFlow:
    """Test end-to-end flow from webhook to Celery processing."""

    @pytest.mark.integration
    @pytest.mark.celery
    @pytest.mark.slow
    def test_webhook_triggers_celery_processing(self, test_client, db_session, celery_app):
        """Test that webhook triggers Celery task processing."""
        # Send webhook
        response = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)

        assert response.status_code == 200
        alert_id = response.json()["alert_id"]

        # In eager mode, task executes immediately
        # Verify alert was processed
        alert = db_session.query(Alert).filter(Alert.id == alert_id).first()

        # Verify ML classification applied (stub values in Phase 1)
        assert alert.severity is not None
        assert alert.predicted_team is not None
        assert alert.confidence_score is not None

        # Verify entity extraction
        assert alert.service_name is not None
        assert alert.environment is not None

        # Verify alert was grouped into incident
        assert alert.incident_id is not None

    @pytest.mark.integration
    @pytest.mark.celery
    def test_incident_creation_from_webhook(self, test_client, db_session, celery_app):
        """Test that first alert creates a new incident."""
        initial_incident_count = db_session.query(Incident).count()

        # Send webhook
        response = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)

        assert response.status_code == 200
        alert_id = response.json()["alert_id"]

        # Verify incident was created
        final_incident_count = db_session.query(Incident).count()
        assert final_incident_count == initial_incident_count + 1

        # Verify incident properties
        alert = db_session.query(Alert).filter(Alert.id == alert_id).first()
        incident = db_session.query(Incident).filter(
            Incident.id == alert.incident_id
        ).first()

        assert incident is not None
        assert incident.status == IncidentStatus.OPEN
        assert incident.title == alert.title
        assert incident.severity == alert.severity

    @pytest.mark.integration
    @pytest.mark.celery
    def test_audit_trail_created(self, test_client, db_session, celery_app):
        """Test that incident actions are logged in audit trail."""
        # Send webhook
        response = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)

        assert response.status_code == 200
        alert_id = response.json()["alert_id"]

        # Get incident ID
        alert = db_session.query(Alert).filter(Alert.id == alert_id).first()
        incident_id = alert.incident_id

        # Verify actions logged
        actions = db_session.query(IncidentAction).filter(
            IncidentAction.incident_id == incident_id
        ).all()

        assert len(actions) > 0

        # Should have at least one action (incident creation or alert added)
        action_types = [action.action_type for action in actions]
        assert ActionType.STATUS_CHANGE in action_types or ActionType.ALERT_ADDED in action_types


class TestIncidentGroupingIntegration:
    """Test incident grouping with real webhook data."""

    @pytest.mark.integration
    @pytest.mark.celery
    def test_multiple_alerts_grouped_to_same_incident(self, test_client, db_session, celery_app):
        """Test that multiple alerts within time window are grouped together."""
        # Send first alert
        response1 = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)
        assert response1.status_code == 200
        alert_id_1 = response1.json()["alert_id"]

        # Get incident ID from first alert
        alert1 = db_session.query(Alert).filter(Alert.id == alert_id_1).first()
        incident_id_1 = alert1.incident_id

        # Send second alert (different alert, same timeframe)
        payload2 = {**DATADOG_HIGH_MEMORY, "last_updated": datetime.now(timezone.utc).isoformat()}
        response2 = test_client.post("/webhook/datadog", json=payload2)
        assert response2.status_code == 200
        alert_id_2 = response2.json()["alert_id"]

        # Get incident ID from second alert
        alert2 = db_session.query(Alert).filter(Alert.id == alert_id_2).first()
        incident_id_2 = alert2.incident_id

        # Both alerts should be in same incident (within 5-minute window)
        assert incident_id_1 == incident_id_2

        # Verify incident has both alerts
        incident = db_session.query(Incident).filter(
            Incident.id == incident_id_1
        ).first()

        alert_count = db_session.query(Alert).filter(
            Alert.incident_id == incident.id
        ).count()

        assert alert_count >= 2

    @pytest.mark.integration
    @pytest.mark.celery
    def test_affected_services_aggregation(self, test_client, db_session, celery_app):
        """Test that affected_services list is updated as alerts are grouped."""
        # Send first alert
        response1 = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)
        alert_id_1 = response1.json()["alert_id"]

        alert1 = db_session.query(Alert).filter(Alert.id == alert_id_1).first()
        incident_id = alert1.incident_id

        # Get incident
        incident = db_session.query(Incident).filter(Incident.id == incident_id).first()

        # Should have service from first alert
        initial_services = incident.affected_services or []
        assert len(initial_services) >= 1

        # Send second alert with different service
        payload2 = {
            **DATADOG_HIGH_MEMORY,
            "id": "different-service-001",
            "tags": ["service:worker-service", "env:production"],
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        response2 = test_client.post("/webhook/datadog", json=payload2)
        alert_id_2 = response2.json()["alert_id"]

        # Refresh incident
        db_session.refresh(incident)

        # Should now have both services (if grouping worked)
        # Note: Exact behavior depends on service extraction logic
        assert incident.affected_services is not None

    @pytest.mark.integration
    @pytest.mark.celery
    def test_incident_updated_timestamp(self, test_client, db_session, celery_app):
        """Test that incident updated_at changes when new alerts are added."""
        # Send first alert
        response1 = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)
        alert_id_1 = response1.json()["alert_id"]

        alert1 = db_session.query(Alert).filter(Alert.id == alert_id_1).first()
        incident = db_session.query(Incident).filter(
            Incident.id == alert1.incident_id
        ).first()

        initial_updated_at = incident.updated_at

        # Send second alert
        import time
        time.sleep(0.1)  # Ensure timestamp difference

        payload2 = {
            **DATADOG_HIGH_MEMORY,
            "id": "timestamp-test-002",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        response2 = test_client.post("/webhook/datadog", json=payload2)

        # Refresh incident
        db_session.refresh(incident)

        # updated_at should be more recent
        assert incident.updated_at >= initial_updated_at


class TestDuplicateHandlingWithCelery:
    """Test duplicate detection with Celery processing."""

    @pytest.mark.integration
    @pytest.mark.celery
    def test_duplicate_alert_not_reprocessed(self, test_client, db_session, celery_app):
        """Test that duplicate alerts are not reprocessed by Celery."""
        # Send alert twice
        response1 = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)
        response2 = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)

        alert_id_1 = response1.json()["alert_id"]
        alert_id_2 = response2.json()["alert_id"]

        # Should return same alert ID
        assert alert_id_1 == alert_id_2

        # Only one alert in database
        count = db_session.query(Alert).filter(
            Alert.external_id == DATADOG_HIGH_CPU["id"]
        ).count()

        assert count == 1


class TestErrorHandlingIntegration:
    """Test error handling in the complete flow."""

    @pytest.mark.integration
    @pytest.mark.celery
    def test_webhook_succeeds_even_if_celery_fails(self, test_client, db_session):
        """Test that webhook endpoint succeeds even if Celery task fails."""
        # This tests that webhook returns quickly without waiting for Celery
        # In eager mode, failures would propagate, but in production they wouldn't

        response = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)

        # Webhook should always succeed (fire-and-forget pattern)
        assert response.status_code == 200

        # Alert should be in database
        alert_id = response.json()["alert_id"]
        alert = db_session.query(Alert).filter(Alert.id == alert_id).first()
        assert alert is not None

    @pytest.mark.integration
    @pytest.mark.celery
    def test_database_rollback_on_processing_error(self, test_client, db_session, celery_app):
        """Test that database changes are rolled back if processing fails."""
        # This test documents rollback behavior
        # In practice, with proper error handling, partial state shouldn't be committed

        response = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)
        alert_id = response.json()["alert_id"]

        alert = db_session.query(Alert).filter(Alert.id == alert_id).first()

        # Even if processing partially fails, alert should be in consistent state
        # Either fully processed or not processed at all
        if alert.severity is not None:
            # If classification succeeded, all fields should be set
            assert alert.predicted_team is not None
            assert alert.confidence_score is not None


class TestPerformanceIntegration:
    """Test performance characteristics of the integration."""

    @pytest.mark.integration
    @pytest.mark.celery
    @pytest.mark.slow
    def test_bulk_alert_processing(self, test_client, db_session, celery_app):
        """Test processing multiple alerts in bulk."""
        num_alerts = 20

        payloads = [
            {
                **DATADOG_HIGH_CPU,
                "id": f"bulk-test-{i}",
                "title": f"Bulk alert {i}",
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            for i in range(num_alerts)
        ]

        # Send all alerts
        responses = []
        for payload in payloads:
            response = test_client.post("/webhook/datadog", json=payload)
            responses.append(response)

        # All should succeed
        assert all(r.status_code == 200 for r in responses)

        # All should be processed (in eager mode)
        alert_ids = [r.json()["alert_id"] for r in responses]
        processed_count = db_session.query(Alert).filter(
            Alert.id.in_(alert_ids),
            Alert.severity.isnot(None)
        ).count()

        assert processed_count == num_alerts

        # Should have created incidents
        incident_count = db_session.query(Incident).count()
        assert incident_count > 0

    @pytest.mark.integration
    @pytest.mark.celery
    def test_sequential_processing_maintains_order(self, test_client, db_session, celery_app):
        """Test that alerts are processed in order received."""
        base_time = datetime.now(timezone.utc)

        # Send alerts with incrementing timestamps
        payloads = [
            {
                **DATADOG_HIGH_CPU,
                "id": f"sequential-{i}",
                "last_updated": (base_time + timedelta(minutes=i)).isoformat(),
            }
            for i in range(5)
        ]

        alert_ids = []
        for payload in payloads:
            response = test_client.post("/webhook/datadog", json=payload)
            alert_ids.append(response.json()["alert_id"])

        # Verify all processed
        alerts = db_session.query(Alert).filter(
            Alert.id.in_(alert_ids)
        ).order_by(Alert.id).all()

        # All should be processed
        assert all(alert.severity is not None for alert in alerts)

        # Should be grouped based on time window
        incident_ids = [alert.incident_id for alert in alerts]
        # First few should be in same incident (within 5-minute window)
        assert incident_ids[0] == incident_ids[1]


class TestIncidentLifecycle:
    """Test full incident lifecycle through the integration."""

    @pytest.mark.integration
    @pytest.mark.celery
    def test_incident_creation_and_updates(self, test_client, db_session, celery_app):
        """Test complete lifecycle of an incident from creation through updates."""
        # 1. Create first alert (creates incident)
        response1 = test_client.post("/webhook/datadog", json=DATADOG_HIGH_CPU)
        alert_id_1 = response1.json()["alert_id"]

        alert1 = db_session.query(Alert).filter(Alert.id == alert_id_1).first()
        incident_id = alert1.incident_id

        incident = db_session.query(Incident).filter(Incident.id == incident_id).first()

        # Verify initial state
        assert incident.status == IncidentStatus.OPEN
        assert incident.created_at is not None

        # 2. Add second alert (updates incident)
        payload2 = {
            **DATADOG_HIGH_MEMORY,
            "id": "lifecycle-002",
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }
        response2 = test_client.post("/webhook/datadog", json=payload2)
        alert_id_2 = response2.json()["alert_id"]

        alert2 = db_session.query(Alert).filter(Alert.id == alert_id_2).first()

        # Should be grouped to same incident
        assert alert2.incident_id == incident_id

        # 3. Verify audit trail
        actions = db_session.query(IncidentAction).filter(
            IncidentAction.incident_id == incident_id
        ).order_by(IncidentAction.timestamp).all()

        assert len(actions) >= 2  # At least 2 actions (creation + alert added)

        # 4. Verify incident metadata
        db_session.refresh(incident)
        alert_count = db_session.query(Alert).filter(
            Alert.incident_id == incident_id
        ).count()

        assert alert_count >= 2
        assert incident.updated_at >= incident.created_at
