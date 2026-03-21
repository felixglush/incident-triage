"""
Integration tests for connector endpoints.
"""
import pytest

from app.models import Connector, ConnectorStatus, ConnectorSyncStatus, RunbookChunk, SourceDocument
from app.services.notion_connector import NotionPage


@pytest.mark.integration
class TestConnectorEndpoints:
    def test_list_connectors(self, test_client, db_session):
        connector = Connector(
            id="slack",
            name="Slack",
            provider="slack",
            status=ConnectorStatus.NOT_CONNECTED,
            detail="Incident history",
        )
        db_session.add(connector)
        db_session.commit()

        response = test_client.get("/connectors")
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] >= 1

    def test_configure_notion_connector_requires_root_page(self, test_client, db_session):
        connector = Connector(
            id="notion",
            name="Notion",
            provider="notion",
            status=ConnectorStatus.NOT_CONNECTED,
            detail="Runbook sync",
        )
        db_session.add(connector)
        db_session.commit()

        response = test_client.post("/connectors/notion/configure", json={})
        assert response.status_code == 422

    def test_configure_notion_connector_persists_root_pages(self, test_client, db_session):
        connector = Connector(
            id="notion",
            name="Notion",
            provider="notion",
            status=ConnectorStatus.NOT_CONNECTED,
            detail="Runbook sync",
        )
        db_session.add(connector)
        db_session.commit()

        response = test_client.post(
            "/connectors/notion/configure",
            json={
                "root_pages": [
                    "https://www.notion.so/OpsRelay-Knowledge-1234567890abcdef1234567890abcdef",
                    "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                ]
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["connector"]["status"] == ConnectorStatus.CONNECTED.value
        assert payload["connector"]["root_pages"] == [
            {
                "page_id": "12345678-90ab-cdef-1234-567890abcdef",
                "page_url": "https://www.notion.so/OpsRelay-Knowledge-1234567890abcdef1234567890abcdef",
            },
            {
                "page_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "page_url": None,
            },
        ]

        db_session.refresh(connector)
        assert connector.root_page_id == "12345678-90ab-cdef-1234-567890abcdef"
        assert connector.status == ConnectorStatus.CONNECTED
        assert connector.config_json["root_pages"][1]["page_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def test_sync_notion_connector_ingests_chunks_and_updates_status(self, test_client, db_session, monkeypatch):
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
                    },
                    {
                        "page_id": "ffffffff-1111-2222-3333-444444444444",
                        "page_url": "https://www.notion.so/Runbooks-ffffffff111122223333444444444444",
                    },
                ]
            },
        )
        db_session.add(connector)
        db_session.commit()
        monkeypatch.setenv("NOTION_TOKEN", "secret_test")

        pages = [
            NotionPage(
                page_id="12345678-90ab-cdef-1234-567890abcdef",
                title="OpsRelay Knowledge",
                url="https://www.notion.so/OpsRelay-Knowledge-1234567890abcdef1234567890abcdef",
                last_edited_time="2026-03-14T00:00:00.000Z",
                parent_page_id=None,
                markdown="# OpsRelay Knowledge\n\nRoot content for sync.",
            ),
            NotionPage(
                page_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                title="Database Pool Saturation",
                url="https://www.notion.so/Database-Pool-Saturation-aaaaaaaabbbbccccddddeeeeeeeeeeee",
                last_edited_time="2026-03-14T00:01:00.000Z",
                parent_page_id="12345678-90ab-cdef-1234-567890abcdef",
                markdown="# Database Pool Saturation\n\nCheck connection counts and restart the pooler.",
            ),
        ]

        class FakeNotionClient:
            def __init__(self, *args, **kwargs):
                pass

            def get_workspace_name(self):
                return "Felix Workspace"

            def collect_page_tree(self, root_page_id):
                if root_page_id == "ffffffff-1111-2222-3333-444444444444":
                    return [
                        NotionPage(
                            page_id="ffffffff-1111-2222-3333-444444444444",
                            title="Runbooks",
                            url="https://www.notion.so/Runbooks-ffffffff111122223333444444444444",
                            last_edited_time="2026-03-14T00:02:00.000Z",
                            parent_page_id=None,
                            markdown="# Runbooks\n\nShared runbook index.",
                        )
                    ]
                return list(pages)

        monkeypatch.setattr("app.services.notion_connector.NotionClient", FakeNotionClient)

        response = test_client.post("/connectors/notion/sync")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "accepted"

        db_session.refresh(connector)
        assert connector.last_sync_status == ConnectorSyncStatus.SUCCEEDED
        assert connector.workspace_name == "Felix Workspace"

        chunks = (
            db_session.query(RunbookChunk)
            .filter(RunbookChunk.source == "notion")
            .order_by(RunbookChunk.source_document.asc(), RunbookChunk.chunk_index.asc())
            .all()
        )
        source_documents = (
            db_session.query(SourceDocument)
            .filter(SourceDocument.source == "notion")
            .order_by(SourceDocument.source_document.asc())
            .all()
        )
        assert len(chunks) >= 2
        assert len(source_documents) == 3
        assert any(chunk.title == "Database Pool Saturation" for chunk in chunks)
        assert all(chunk.source_uri for chunk in chunks)
        assert any(doc.title == "Database Pool Saturation" for doc in source_documents)
        assert any("Check connection counts" in doc.content for doc in source_documents)

        listing = test_client.get("/connectors/notion/pages", params={"limit": 1, "offset": 0})
        assert listing.status_code == 200
        listing_payload = listing.json()
        assert listing_payload["total"] == 3
        assert listing_payload["items"][0]["title"] in {
            "Database Pool Saturation",
            "OpsRelay Knowledge",
            "Runbooks",
        }

    def test_sync_notion_connector_reconciles_removed_pages(self, test_client, db_session, monkeypatch):
        connector = Connector(
            id="notion",
            name="Notion",
            provider="notion",
            status=ConnectorStatus.CONNECTED,
            detail="Runbook sync",
            root_page_id="12345678-90ab-cdef-1234-567890abcdef",
            config_json={
                "root_pages": [
                    {"page_id": "12345678-90ab-cdef-1234-567890abcdef", "page_url": "https://www.notion.so/root"},
                    {"page_id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff", "page_url": "https://www.notion.so/child-root"},
                ]
            },
        )
        db_session.add(connector)
        db_session.commit()
        monkeypatch.setenv("NOTION_TOKEN", "secret_test")

        state = {
            "pages": [
                NotionPage(
                    page_id="12345678-90ab-cdef-1234-567890abcdef",
                    title="OpsRelay Knowledge",
                    url="https://www.notion.so/root",
                    last_edited_time="2026-03-14T00:00:00.000Z",
                    parent_page_id=None,
                    markdown="# OpsRelay Knowledge\n\nRoot content.",
                ),
                NotionPage(
                    page_id="bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                    title="Child Page",
                    url="https://www.notion.so/child",
                    last_edited_time="2026-03-14T00:00:00.000Z",
                    parent_page_id="12345678-90ab-cdef-1234-567890abcdef",
                    markdown="# Child Page\n\nOriginal content.",
                ),
            ]
        }

        class FakeNotionClient:
            def __init__(self, *args, **kwargs):
                pass

            def get_workspace_name(self):
                return "Felix Workspace"

            def collect_page_tree(self, _root_page_id):
                return list(state["pages"])

        monkeypatch.setattr("app.services.notion_connector.NotionClient", FakeNotionClient)

        first = test_client.post("/connectors/notion/sync")
        assert first.status_code == 200

        state["pages"] = [
            NotionPage(
                page_id="12345678-90ab-cdef-1234-567890abcdef",
                title="OpsRelay Knowledge",
                url="https://www.notion.so/root",
                last_edited_time="2026-03-14T00:05:00.000Z",
                parent_page_id=None,
                markdown="# OpsRelay Knowledge\n\nUpdated root content.",
            )
        ]

        second = test_client.post("/connectors/notion/sync")
        assert second.status_code == 200

        chunks = db_session.query(RunbookChunk).filter(RunbookChunk.source == "notion").all()
        documents = db_session.query(SourceDocument).filter(SourceDocument.source == "notion").all()
        assert {chunk.source_document for chunk in chunks} == {"12345678-90ab-cdef-1234-567890abcdef"}
        assert {document.source_document for document in documents} == {"12345678-90ab-cdef-1234-567890abcdef"}
        assert any("Updated root content." in chunk.content for chunk in chunks)

    def test_sync_notion_connector_marks_failed_when_token_missing(self, test_client, db_session, monkeypatch):
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

        response = test_client.post("/connectors/notion/sync")
        assert response.status_code == 200
        assert response.json()["status"] == "accepted"

        db_session.refresh(connector)
        assert connector.last_sync_status == ConnectorSyncStatus.FAILED
        assert connector.last_sync_error == "NOTION_TOKEN is not configured"
