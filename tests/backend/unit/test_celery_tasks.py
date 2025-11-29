"""
Unit tests for Celery tasks.

Tests alert processing and incident grouping logic with eager mode (synchronous).
"""

from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest
import requests

from app.models import Alert, Incident, IncidentAction, ActionType, IncidentStatus, SeverityLevel
from app.workers.tasks import group_alerts_into_incidents, process_alert
from tests.backend.fixtures.factories import AlertFactory, IncidentFactory, configure_factories


class TestProcessAlertTask:
    """Test suite for the process_alert Celery task."""

    @pytest.mark.celery
    @pytest.mark.database
    @mock.patch('app.workers.tasks.requests.post')
    def test_process_alert_success(self, mock_post, db_session, celery_app):
        """Test successful alert processing with ML classification."""
        configure_factories(db_session)

        # Mock ML service responses
        mock_post.side_effect = [
            # First call: /classify
            mock.Mock(
                status_code=200,
                json=lambda: {
                    "severity": "critical",
                    "team": "infrastructure",
                    "confidence": 0.92
                }
            ),
            # Second call: /extract-entities
            mock.Mock(
                status_code=200,
                json=lambda: {
                    "service_name": "postgres-primary",
                    "environment": "production",
                    "region": "us-east-1",
                    "error_code": None
                }
            )
        ]

        # Create an unprocessed alert
        alert = AlertFactory(
            title="Database connection pool exhausted",
            message="PostgreSQL production us-east-1 max connections reached",
            severity=None,
            predicted_team=None,
            confidence_score=None,
            service_name=None,
        )
        db_session.commit()

        # Process alert (eager mode runs synchronously)
        result = process_alert.delay(alert.id)

        assert result.successful()

        # Verify ML service was called
        assert mock_post.call_count == 2

        # Verify first call (classification)
        classify_call = mock_post.call_args_list[0]
        assert "/classify" in classify_call[0][0]
        assert "Database connection pool exhausted" in classify_call[1]["json"]["text"]

        # Refresh alert from database
        db_session.refresh(alert)

        # Verify ML classification results
        assert alert.severity == SeverityLevel.CRITICAL
        assert alert.predicted_team == "infrastructure"
        assert alert.confidence_score == 0.92

        # Verify entity extraction results
        assert alert.service_name == "postgres-primary"
        assert alert.environment == "production"
        assert alert.region == "us-east-1"

        # Verify alert was grouped into an incident
        assert alert.incident_id is not None

    @pytest.mark.unit
    @pytest.mark.celery
    @pytest.mark.database
    def test_process_alert_not_found(self, db_session, celery_app):
        """Test handling of non-existent alert ID."""
        result = process_alert.delay(99999)  # Non-existent ID

        assert result.successful()
        result_data = result.get()
        assert result_data["status"] == "failed"
        assert "not found" in result_data["error"].lower()

    @pytest.mark.celery
    @pytest.mark.database
    @mock.patch('app.workers.tasks.requests.post')
    def test_process_alert_handles_ml_service_failure(self, mock_post, db_session, celery_app):
        """Test graceful degradation when ML service fails."""
        configure_factories(db_session)

        # Simulate ML service timeout
        mock_post.side_effect = requests.Timeout("ML service timeout")

        alert = AlertFactory(
            severity=None,
            predicted_team=None,
            confidence_score=None
        )
        db_session.commit()

        # Should still succeed with fallback values
        result = process_alert.delay(alert.id)

        assert result.successful()

        db_session.refresh(alert)

        # Verify fallback values were used
        assert alert.severity == SeverityLevel.WARNING
        assert alert.predicted_team == "backend"
        assert alert.confidence_score == 0.0

        # Alert should still be grouped into incident
        assert alert.incident_id is not None

    @pytest.mark.celery
    @pytest.mark.database
    @mock.patch('app.workers.tasks.requests.post')
    def test_process_alert_handles_ml_service_error_response(self, mock_post, db_session, celery_app):
        """Test handling of ML service returning error status code."""
        configure_factories(db_session)

        # Simulate ML service returning 500 error
        mock_response = mock.Mock()
        mock_response.raise_for_status.side_effect = requests.HTTPError("500 Server Error")
        mock_post.return_value = mock_response

        alert = AlertFactory(severity=None)
        db_session.commit()

        # Should succeed with fallback values
        result = process_alert.delay(alert.id)

        assert result.successful()

        db_session.refresh(alert)

        # Verify fallback classification
        assert alert.severity == SeverityLevel.WARNING
        assert alert.predicted_team == "backend"
        assert alert.confidence_score == 0.0

    @pytest.mark.unit
    @pytest.mark.celery
    @pytest.mark.database
    @mock.patch('app.workers.tasks.requests.post')
    def test_process_alert_idempotency(self, mock_post, db_session, celery_app):
        """Test that processing the same alert twice is idempotent."""
        configure_factories(db_session)

        # Mock ML service responses for both calls
        mock_post.side_effect = [
            mock.Mock(status_code=200, json=lambda: {"severity": "warning", "team": "backend", "confidence": 0.7}),
            mock.Mock(status_code=200, json=lambda: {"service_name": None, "environment": None, "region": None, "error_code": None}),
            mock.Mock(status_code=200, json=lambda: {"severity": "warning", "team": "backend", "confidence": 0.7}),
            mock.Mock(status_code=200, json=lambda: {"service_name": None, "environment": None, "region": None, "error_code": None}),
        ]

        alert = AlertFactory(severity=None)
        db_session.commit()

        # Process twice
        result1 = process_alert.delay(alert.id)
        result2 = process_alert.delay(alert.id)

        assert result1.successful()
        assert result2.successful()

        db_session.refresh(alert)

        # Should still have consistent state
        assert alert.severity == SeverityLevel.WARNING
        assert alert.incident_id is not None

    @pytest.mark.celery
    @pytest.mark.database
    @mock.patch('app.workers.tasks.requests.post')
    def test_process_alert_creates_incident_action(self, mock_post, db_session, celery_app):
        """Test that processing creates audit trail entries."""
        configure_factories(db_session)

        # Mock ML service responses
        mock_post.side_effect = [
            mock.Mock(status_code=200, json=lambda: {"severity": "warning", "team": "backend", "confidence": 0.7}),
            mock.Mock(status_code=200, json=lambda: {"service_name": None, "environment": None, "region": None, "error_code": None}),
        ]

        alert = AlertFactory(severity=None)
        db_session.commit()

        process_alert.delay(alert.id)

        db_session.refresh(alert)

        # Verify incident action was created
        actions = db_session.query(IncidentAction).filter(
            IncidentAction.incident_id == alert.incident_id
        ).all()

        assert len(actions) > 0
        # First alert creates new incident, which logs STATUS_CHANGE action
        assert any(action.action_type == ActionType.STATUS_CHANGE for action in actions)


class TestIncidentGroupingLogic:
    """Test suite for incident grouping algorithm."""

    @pytest.mark.unit
    @pytest.mark.database
    def test_first_alert_creates_new_incident(self, db_session):
        """Test that first alert creates a new incident."""
        configure_factories(db_session)

        alert = AlertFactory(incident_id=None)
        db_session.commit()

        incident_id = group_alerts_into_incidents(db_session, alert)

        assert incident_id is not None

        incident = db_session.query(Incident).filter(Incident.id == incident_id).first()
        assert incident is not None
        assert incident.title == alert.title
        assert incident.status == IncidentStatus.OPEN

        # Verify alert is linked to incident
        db_session.refresh(alert)
        assert alert.incident_id == incident_id

    @pytest.mark.unit
    @pytest.mark.database
    def test_alerts_within_window_grouped_together(self, db_session):
        """Test that alerts within 5-minute window are grouped together."""
        configure_factories(db_session)

        # Create base time
        base_time = datetime.now(timezone.utc)

        # Create first alert and its incident
        alert1 = AlertFactory(
            alert_timestamp=base_time,
            incident_id=None,
        )
        db_session.commit()
        incident_id_1 = group_alerts_into_incidents(db_session, alert1)

        # Create second alert 2 minutes later (within window)
        alert2 = AlertFactory(
            alert_timestamp=base_time + timedelta(minutes=2),
            incident_id=None,
        )
        db_session.commit()
        incident_id_2 = group_alerts_into_incidents(db_session, alert2)

        # Should be grouped into same incident
        assert incident_id_1 == incident_id_2

        db_session.refresh(alert1)
        db_session.refresh(alert2)

        assert alert1.incident_id == alert2.incident_id

    @pytest.mark.unit
    @pytest.mark.database
    def test_alerts_outside_window_create_separate_incidents(self, db_session):
        """Test that alerts outside 5-minute window create separate incidents."""
        configure_factories(db_session)

        base_time = datetime.now(timezone.utc)

        # Create first alert
        alert1 = AlertFactory(
            alert_timestamp=base_time,
            incident_id=None,
        )
        db_session.commit()
        incident_id_1 = group_alerts_into_incidents(db_session, alert1)

        # Create second alert 10 minutes later (outside window)
        alert2 = AlertFactory(
            alert_timestamp=base_time + timedelta(minutes=10),
            incident_id=None,
        )
        db_session.commit()
        incident_id_2 = group_alerts_into_incidents(db_session, alert2)

        # Should create separate incidents
        assert incident_id_1 != incident_id_2

    @pytest.mark.unit
    @pytest.mark.database
    def test_affected_services_updated(self, db_session):
        """Test that incident affected_services list is updated when alerts are added."""
        configure_factories(db_session)

        base_time = datetime.now(timezone.utc)

        # First alert with service A
        alert1 = AlertFactory(
            alert_timestamp=base_time,
            service_name="service-a",
            incident_id=None,
        )
        db_session.commit()
        incident_id = group_alerts_into_incidents(db_session, alert1)

        # Second alert with service B (within window)
        alert2 = AlertFactory(
            alert_timestamp=base_time + timedelta(minutes=1),
            service_name="service-b",
            incident_id=None,
        )
        db_session.commit()
        group_alerts_into_incidents(db_session, alert2)

        # Refresh incident from database to get updated affected_services
        db_session.expire_all()  # Clear cache
        incident = db_session.query(Incident).filter(Incident.id == incident_id).first()

        # Check incident has both services
        assert "service-a" in incident.affected_services
        assert "service-b" in incident.affected_services

    @pytest.mark.unit
    @pytest.mark.database
    def test_duplicate_services_not_added(self, db_session):
        """Test that duplicate services are not added to affected_services."""
        configure_factories(db_session)

        base_time = datetime.now(timezone.utc)

        # Two alerts for same service
        alert1 = AlertFactory(
            alert_timestamp=base_time,
            service_name="api-service",
            incident_id=None,
        )
        db_session.commit()
        incident_id = group_alerts_into_incidents(db_session, alert1)

        alert2 = AlertFactory(
            alert_timestamp=base_time + timedelta(seconds=30),
            service_name="api-service",
            incident_id=None,
        )
        db_session.commit()
        group_alerts_into_incidents(db_session, alert2)

        incident = db_session.query(Incident).filter(Incident.id == incident_id).first()

        # Service should appear only once
        assert incident.affected_services.count("api-service") == 1

    @pytest.mark.unit
    @pytest.mark.database
    def test_resolved_incidents_not_used_for_grouping(self, db_session):
        """Test that resolved incidents are not considered for grouping new alerts."""
        configure_factories(db_session)

        base_time = datetime.now(timezone.utc)

        # Create resolved incident
        resolved_incident = IncidentFactory(
            status=IncidentStatus.RESOLVED,
            created_at=base_time,
        )
        db_session.commit()

        # Create new alert (within time window of resolved incident)
        alert = AlertFactory(
            alert_timestamp=base_time + timedelta(minutes=1),
            incident_id=None,
        )
        db_session.commit()
        incident_id = group_alerts_into_incidents(db_session, alert)

        # Should create NEW incident, not add to resolved one
        assert incident_id != resolved_incident.id

    @pytest.mark.unit
    @pytest.mark.database
    def test_incident_action_logged(self, db_session):
        """Test that incident actions are logged when alerts are grouped."""
        configure_factories(db_session)

        alert = AlertFactory(incident_id=None)
        db_session.commit()

        incident_id = group_alerts_into_incidents(db_session, alert)

        # Check that action was logged
        actions = db_session.query(IncidentAction).filter(
            IncidentAction.incident_id == incident_id
        ).all()

        assert len(actions) >= 1
        # First action should be incident creation
        assert actions[0].action_type in [ActionType.STATUS_CHANGE, ActionType.ALERT_ADDED]


class TestCeleryTaskRetryLogic:
    """Test Celery task retry and error handling."""

    @pytest.mark.unit
    def test_task_retry_configuration(self):
        """Test that process_alert task is configured with retry settings."""
        from app.workers.tasks import process_alert

        # Verify task has retry configuration
        assert hasattr(process_alert, 'max_retries')
        assert process_alert.max_retries == 3

        # Verify task is bound (needed for self.retry())
        # In Celery, bound tasks have access to task request context
        assert hasattr(process_alert, 'request_stack')

        # Note: Actual retry behavior cannot be tested in eager mode
        # since eager_propagates=True causes exceptions to be raised instead
        # of triggering retries. Retry logic is tested in production with real workers.


class TestIncidentGroupingEdgeCases:
    """Test edge cases in incident grouping."""

    @pytest.mark.unit
    @pytest.mark.database
    def test_null_service_name_handling(self, db_session):
        """Test grouping with null service_name."""
        configure_factories(db_session)

        alert = AlertFactory(
            service_name=None,
            incident_id=None,
        )
        db_session.commit()

        incident_id = group_alerts_into_incidents(db_session, alert)

        incident = db_session.query(Incident).filter(Incident.id == incident_id).first()

        # Should handle null service gracefully
        assert incident is not None
        assert alert.service_name is None

    @pytest.mark.unit
    @pytest.mark.database
    def test_concurrent_grouping_same_incident(self, db_session):
        """Test that concurrent alerts can be grouped to same incident."""
        configure_factories(db_session)

        base_time = datetime.now(timezone.utc)

        # Create alerts with same timestamp
        alert1 = AlertFactory(alert_timestamp=base_time, incident_id=None)
        alert2 = AlertFactory(alert_timestamp=base_time, incident_id=None)
        db_session.commit()

        incident_id_1 = group_alerts_into_incidents(db_session, alert1)
        incident_id_2 = group_alerts_into_incidents(db_session, alert2)

        # Both should be grouped to same incident
        assert incident_id_1 == incident_id_2
