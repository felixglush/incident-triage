"""
Integration tests for dashboard endpoints.
"""
from datetime import datetime, timezone

import pytest

from app.models import Incident, Alert, IncidentStatus, SeverityLevel


@pytest.mark.integration
class TestDashboardMetrics:
    def test_dashboard_metrics(self, test_client, db_session):
        open_incident = Incident(
            title="Open incident",
            severity=SeverityLevel.CRITICAL,
            status=IncidentStatus.OPEN,
            created_at=datetime.now(timezone.utc),
        )
        resolved_incident = Incident(
            title="Resolved incident",
            severity=SeverityLevel.CRITICAL,
            status=IncidentStatus.RESOLVED,
            created_at=datetime.now(timezone.utc),
            resolved_at=datetime.now(timezone.utc),
            time_to_acknowledge=120,
            time_to_resolve=600,
        )
        db_session.add_all([open_incident, resolved_incident])
        db_session.flush()

        alert = Alert(
            external_id="alert-untriaged",
            source="datadog",
            title="CPU high",
            message="",
            raw_payload={"id": "alert-untriaged"},
            alert_timestamp=datetime.now(timezone.utc),
        )
        db_session.add(alert)
        db_session.commit()

        response = test_client.get("/dashboard/metrics")
        assert response.status_code == 200
        payload = response.json()

        assert payload["active_incidents"] == 1
        assert payload["critical_incidents"] == 1
        assert payload["untriaged_alerts"] == 1
        assert payload["mtta_minutes"] is not None
        assert payload["mttr_minutes"] is not None
