"""
Integration tests for connector endpoints.
"""
import pytest

from app.models import Connector, ConnectorStatus


@pytest.mark.integration
class TestConnectorEndpoints:
    def test_list_connectors(self, test_client, db_session):
        connector = Connector(
            id="slack",
            name="Slack",
            status=ConnectorStatus.NOT_CONNECTED,
            detail="Incident history",
        )
        db_session.add(connector)
        db_session.commit()

        response = test_client.get("/connectors")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] >= 1

    def test_connect_connector_updates_status(self, test_client, db_session):
        connector = Connector(
            id="notion",
            name="Notion",
            status=ConnectorStatus.NOT_CONNECTED,
            detail="Runbook sync",
        )
        db_session.add(connector)
        db_session.commit()

        response = test_client.post("/connectors/notion/connect")
        assert response.status_code == 200
        payload = response.json()
        assert payload["new_status"] == ConnectorStatus.CONNECTED.value

        db_session.refresh(connector)
        assert connector.status == ConnectorStatus.CONNECTED
