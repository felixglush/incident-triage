import pytest

from app.models import Connector, ConnectorStatus, ConnectorSyncStatus
from app.services.notion_connector import (
    NotionSyncError,
    normalize_notion_page_id,
    sync_notion_connector,
)


@pytest.mark.unit
def test_normalize_notion_page_id_from_url():
    url = "https://www.notion.so/OpsRelay-Knowledge-1234567890abcdef1234567890abcdef?pvs=4"
    assert normalize_notion_page_id(url) == "12345678-90ab-cdef-1234-567890abcdef"


@pytest.mark.unit
def test_normalize_notion_page_id_from_raw_id():
    raw_id = "1234567890abcdef1234567890abcdef"
    assert normalize_notion_page_id(raw_id) == "12345678-90ab-cdef-1234-567890abcdef"


@pytest.mark.unit
def test_normalize_notion_page_id_rejects_invalid_values():
    with pytest.raises(ValueError):
        normalize_notion_page_id("not-a-valid-page")


@pytest.mark.integration
def test_sync_notion_connector_marks_failed_when_token_missing(db_session, monkeypatch):
    connector = Connector(
        id="notion",
        name="Notion",
        provider="notion",
        status=ConnectorStatus.CONNECTED,
        detail="Runbook sync",
        root_page_id="12345678-90ab-cdef-1234-567890abcdef",
        root_page_url="https://www.notion.so/OpsRelay-Knowledge-1234567890abcdef1234567890abcdef",
        config_json={
            "root_pages": [
                {
                    "page_id": "12345678-90ab-cdef-1234-567890abcdef",
                    "page_url": "https://www.notion.so/OpsRelay-Knowledge-1234567890abcdef1234567890abcdef",
                }
            ]
        },
    )
    db_session.add(connector)
    db_session.commit()
    monkeypatch.delenv("NOTION_TOKEN", raising=False)

    with pytest.raises(NotionSyncError, match="NOTION_TOKEN is not configured"):
        sync_notion_connector(db_session)

    db_session.refresh(connector)
    assert connector.last_sync_status == ConnectorSyncStatus.FAILED
    assert connector.last_sync_error == "NOTION_TOKEN is not configured"
