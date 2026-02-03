"""
Integration tests for incident and alert review endpoints.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Incident, Alert, IncidentAction, IncidentStatus, SeverityLevel, ActionType, RunbookChunk


@pytest.mark.integration
class TestIncidentEndpoints:
    def test_list_incidents_with_aggregates(self, test_client, db_session):
        incident = Incident(
            title="Database outage",
            severity=SeverityLevel.CRITICAL,
            status=IncidentStatus.OPEN,
            assigned_team="platform",
            affected_services=["db"],
        )
        db_session.add(incident)
        db_session.flush()

        base_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        alert1 = Alert(
            external_id="alert-1",
            source="datadog",
            title="DB down",
            message="",
            raw_payload={"id": "alert-1"},
            alert_timestamp=base_time,
            incident_id=incident.id,
        )
        alert2 = Alert(
            external_id="alert-2",
            source="datadog",
            title="DB down again",
            message="",
            raw_payload={"id": "alert-2"},
            alert_timestamp=base_time + timedelta(minutes=5),
            incident_id=incident.id,
        )
        db_session.add_all([alert1, alert2])
        db_session.commit()

        response = test_client.get("/incidents")
        assert response.status_code == 200
        data = response.json()

        assert data["total"] >= 1
        items = data["items"]
        assert len(items) >= 1

        record = next(i for i in items if i["id"] == incident.id)
        assert record["alert_count"] == 2
        assert record["last_alert_at"] is not None

    def test_get_incident_detail_includes_alerts_and_actions(self, test_client, db_session):
        incident = Incident(
            title="API latency",
            severity=SeverityLevel.WARNING,
            status=IncidentStatus.OPEN,
            assigned_team="backend",
        )
        db_session.add(incident)
        db_session.flush()

        alert = Alert(
            external_id="alert-3",
            source="sentry",
            title="Latency spike",
            message="",
            raw_payload={"id": "alert-3"},
            alert_timestamp=datetime.now(timezone.utc),
            incident_id=incident.id,
        )
        action = IncidentAction(
            incident_id=incident.id,
            action_type=ActionType.STATUS_CHANGE,
            description="Incident created",
            user="system",
        )
        db_session.add_all([alert, action])
        db_session.commit()

        response = test_client.get(f"/incidents/{incident.id}")
        assert response.status_code == 200
        data = response.json()

        assert data["incident"]["id"] == incident.id
        assert len(data["alerts"]) == 1
        assert len(data["actions"]) == 1

    def test_update_incident_status_creates_action(self, test_client, db_session):
        incident = Incident(
            title="Queue backlog",
            severity=SeverityLevel.ERROR,
            status=IncidentStatus.OPEN,
            assigned_team="backend",
        )
        db_session.add(incident)
        db_session.commit()

        response = test_client.patch(f"/incidents/{incident.id}/status", params={"status": "investigating"})
        assert response.status_code == 200

        db_session.refresh(incident)
        assert incident.status == IncidentStatus.INVESTIGATING

        actions = db_session.query(IncidentAction).filter(IncidentAction.incident_id == incident.id).all()
        assert len(actions) >= 1

    def test_get_similar_incidents(self, test_client, db_session):
        incident = Incident(
            title="Database outage",
            severity=SeverityLevel.CRITICAL,
            status=IncidentStatus.OPEN,
            assigned_team="platform",
            affected_services=["db"],
        )
        similar = Incident(
            title="Database connection errors",
            severity=SeverityLevel.CRITICAL,
            status=IncidentStatus.OPEN,
            assigned_team="platform",
            affected_services=["db"],
        )
        dissimilar = Incident(
            title="Frontend layout regression",
            severity=SeverityLevel.WARNING,
            status=IncidentStatus.OPEN,
            assigned_team="frontend",
            affected_services=["ui"],
        )
        db_session.add_all([incident, similar, dissimilar])
        db_session.commit()

        response = test_client.get(f"/incidents/{incident.id}/similar")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        assert any(item["id"] == similar.id for item in data["items"])
        assert not any(item["id"] == dissimilar.id for item in data["items"])


@pytest.mark.integration
class TestAlertEndpoints:
    def test_list_alerts_with_filters(self, test_client, db_session):
        incident = Incident(
            title="Redis issues",
            severity=SeverityLevel.WARNING,
            status=IncidentStatus.OPEN,
            assigned_team="platform",
        )
        db_session.add(incident)
        db_session.flush()

        alert1 = Alert(
            external_id="alert-4",
            source="datadog",
            title="Redis CPU high",
            message="",
            raw_payload={"id": "alert-4"},
            alert_timestamp=datetime.now(timezone.utc),
            incident_id=incident.id,
            service_name="redis",
            environment="production",
        )
        alert2 = Alert(
            external_id="alert-5",
            source="sentry",
            title="Redis error",
            message="",
            raw_payload={"id": "alert-5"},
            alert_timestamp=datetime.now(timezone.utc),
            incident_id=incident.id,
            service_name="redis",
            environment="staging",
        )
        db_session.add_all([alert1, alert2])
        db_session.commit()

        response = test_client.get("/alerts", params={"source": "datadog"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["external_id"] == "alert-4"


@pytest.mark.integration
class TestIncidentSummaries:
    def test_summarize_incident_cached(self, test_client, db_session):
        incident = Incident(
            title="Queue backlog",
            severity=SeverityLevel.ERROR,
            status=IncidentStatus.OPEN,
            assigned_team="backend",
            affected_services=["queue"],
        )
        db_session.add(incident)
        db_session.flush()

        alert = Alert(
            external_id="alert-summary-1",
            source="datadog",
            title="Queue depth high",
            message="",
            raw_payload={"id": "alert-summary-1", "tags": ["service:queue", "env:production"]},
            alert_timestamp=datetime.now(timezone.utc),
            incident_id=incident.id,
        )
        db_session.add(alert)

        runbook = RunbookChunk(
            source_document="queue-runbook.md",
            chunk_index=0,
            title="Queue Troubleshooting",
            content="Check worker health and backlog depth.",
            doc_metadata={"tags": ["queue"]},
        )
        db_session.add(runbook)
        db_session.commit()

        first = test_client.post(f"/incidents/{incident.id}/summarize")
        assert first.status_code == 200
        payload = first.json()
        assert payload["cached"] is False
        citations = payload["citations"]
        assert any(cite["type"] == "alert" for cite in citations)

        second = test_client.post(f"/incidents/{incident.id}/summarize")
        assert second.status_code == 200
        cached_payload = second.json()
        assert cached_payload["cached"] is True
