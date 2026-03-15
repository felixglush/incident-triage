from datetime import datetime, timezone
import json

import pytest

from app.models import Alert, Incident, IncidentStatus, SeverityLevel
from app.services.chat_orchestrator import ChatContext


@pytest.mark.integration
class TestChatEndpoints:
    @staticmethod
    def _extract_assistant_id(sse_body: str) -> str:
        for line in sse_body.splitlines():
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if data.get("role") == "assistant" and data.get("id"):
                return data["id"]
        raise AssertionError("assistant id not found in SSE payload")

    def test_chat_stream_emits_sse_events(self, test_client, db_session):
        incident = Incident(
            title="Queue worker saturation",
            severity=SeverityLevel.ERROR,
            status=IncidentStatus.OPEN,
            assigned_team="backend",
            affected_services=["queue"],
        )
        db_session.add(incident)
        db_session.flush()

        db_session.add(
            Alert(
                external_id="chat-alert-2",
                source="sentry",
                title="Workers timing out",
                message="Timeouts observed in queue processors.",
                raw_payload={"id": "chat-alert-2", "tags": ["service:queue", "env:production"]},
                alert_timestamp=datetime.now(timezone.utc),
                incident_id=incident.id,
            )
        )
        db_session.commit()

        response = test_client.get(
            "/chat/stream",
            params={"incident_id": incident.id, "message": "what are next steps"},
        )
        assert response.status_code == 200
        body = response.text
        assert "event: tool" in body
        assert "event: assistant_delta" in body
        assert "event: assistant" in body
        assert "event: done" in body

    def test_chat_stream_multiturn_uses_distinct_assistant_ids(self, test_client, db_session):
        incident = Incident(
            title="API saturation",
            severity=SeverityLevel.ERROR,
            status=IncidentStatus.OPEN,
            assigned_team="backend",
            affected_services=["api"],
        )
        db_session.add(incident)
        db_session.flush()

        db_session.add(
            Alert(
                external_id="chat-alert-3",
                source="datadog",
                title="High API latency",
                message="P95 increased",
                raw_payload={"id": "chat-alert-3", "tags": ["service:api", "env:production"]},
                alert_timestamp=datetime.now(timezone.utc),
                incident_id=incident.id,
            )
        )
        db_session.commit()

        first = test_client.get(
            "/chat/stream",
            params={"incident_id": incident.id, "message": "summarize this incident"},
        )
        second = test_client.get(
            "/chat/stream",
            params={"incident_id": incident.id, "message": "what are next steps"},
        )

        assert first.status_code == 200
        assert second.status_code == 200

        first_id = self._extract_assistant_id(first.text)
        second_id = self._extract_assistant_id(second.text)
        assert first_id != second_id

    def test_chat_stream_marks_failed_on_partial_stream_error(self, test_client, db_session, monkeypatch):
        incident = Incident(
            title="Streaming failure case",
            severity=SeverityLevel.ERROR,
            status=IncidentStatus.OPEN,
            assigned_team="backend",
            affected_services=["api"],
        )
        db_session.add(incident)
        db_session.commit()

        from app.api import chat as chat_api

        monkeypatch.setattr(
            chat_api,
            "build_chat_context",
            lambda *args, **kwargs: ChatContext(
                summary="summary",
                citations=[],
                next_steps=["step one"],
                runbook_chunks=[],
            ),
        )

        def _partial_then_fail(**kwargs):
            yield "partial "
            raise RuntimeError("stream interrupted")

        monkeypatch.setattr(chat_api, "stream_assistant_deltas", _partial_then_fail)

        response = test_client.get(
            "/chat/stream",
            params={"incident_id": incident.id, "message": "status"},
        )
        assert response.status_code == 200
        body = response.text
        assert "event: assistant_delta" in body
        assert 'event: tool\ndata: {"tool": "incident.summarize", "status": "failed"}' in body
        assert 'event: done\ndata: {"ok": false}' in body
        assert 'event: tool\ndata: {"tool": "incident.summarize", "status": "done"}' not in body
