"""
Integration tests for runbook endpoints.
"""
from datetime import datetime, timezone

import pytest

from app.models import RunbookChunk


@pytest.mark.integration
class TestRunbookEndpoints:
    def test_list_runbooks(self, test_client, db_session):
        chunk = RunbookChunk(
            source_document="api-gateway.md",
            chunk_index=0,
            title="Restarting the API Gateway",
            content="Runbook content",
            doc_metadata={"tags": ["api", "restart"], "category": "deployment"},
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(chunk)
        db_session.commit()

        response = test_client.get("/runbooks")
        assert response.status_code == 200
        payload = response.json()

        assert payload["total"] >= 1
        item = next(i for i in payload["items"] if i["source"] == "api-gateway.md")
        assert "api" in item["tags"]

    def test_search_runbooks(self, test_client, db_session):
        relevant = RunbookChunk(
            source_document="db-pool.md",
            chunk_index=0,
            title="Database Connection Pool",
            content="Investigate connection pool saturation and restart primary pooler.",
            source="runbooks",
        )
        irrelevant = RunbookChunk(
            source_document="notion-import.md",
            chunk_index=0,
            title="Notion: Onboarding",
            content="Onboarding notes for the customer success team.",
            source="notion",
        )
        db_session.add_all([relevant, irrelevant])
        db_session.commit()

        response = test_client.get("/runbooks/search", params={"q": "connection pool saturation"})
        assert response.status_code == 200
        payload = response.json()

        assert payload["total"] >= 1
        first = payload["items"][0]
        assert first["source"] == "runbooks"
        assert first["source_document"] == "db-pool.md"
        assert "score" in first
