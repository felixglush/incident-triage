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
