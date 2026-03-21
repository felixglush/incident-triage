from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import requests
from sqlalchemy.orm import Session

from app.models import Connector, ConnectorStatus, ConnectorSyncStatus, RunbookChunk
from app.services.ingestion import delete_source_documents, upsert_markdown_document

NOTION_API_BASE = os.getenv("NOTION_API_BASE", "https://api.notion.com/v1")
NOTION_API_VERSION = os.getenv("NOTION_API_VERSION", "2026-03-11")


class NotionSyncError(RuntimeError):
    """Raised when connector sync cannot complete successfully."""


@dataclass
class NotionPage:
    page_id: str
    title: str
    url: str | None
    last_edited_time: str | None
    parent_page_id: str | None
    markdown: str


@dataclass
class NotionRoot:
    page_id: str
    page_url: str | None = None


def normalize_notion_page_id(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("Root page ID or URL is required")

    candidates = re.findall(r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", raw)
    if not candidates:
        raise ValueError("Could not parse a Notion page ID from the provided value")

    page_id = candidates[-1].replace("-", "").lower()
    if len(page_id) != 32:
        raise ValueError("Notion page ID must be 32 hexadecimal characters")

    return (
        f"{page_id[0:8]}-{page_id[8:12]}-{page_id[12:16]}-"
        f"{page_id[16:20]}-{page_id[20:32]}"
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_notion_roots(values: Iterable[str]) -> list[NotionRoot]:
    roots: list[NotionRoot] = []
    seen_page_ids: set[str] = set()
    for value in values:
        raw = (value or "").strip()
        if not raw:
            continue
        page_id = normalize_notion_page_id(raw)
        if page_id in seen_page_ids:
            continue
        seen_page_ids.add(page_id)
        roots.append(
            NotionRoot(
                page_id=page_id,
                page_url=raw if "notion.so" in raw else None,
            )
        )

    if not roots:
        raise ValueError("At least one root page ID or URL is required")

    return roots


def _extract_title(page_payload: dict[str, Any]) -> str:
    properties = page_payload.get("properties") or {}
    for prop in properties.values():
        if not isinstance(prop, dict):
            continue
        if prop.get("type") != "title":
            continue
        parts = prop.get("title") or []
        text = "".join(item.get("plain_text", "") for item in parts if isinstance(item, dict)).strip()
        if text:
            return text
    return page_payload.get("url") or page_payload.get("id") or "Untitled Notion Page"


def _extract_markdown(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return ""
    for key in ("markdown", "content", "text"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    results = payload.get("results")
    if isinstance(results, list):
        parts = [item for item in results if isinstance(item, str)]
        if parts:
            return "\n".join(parts)
    return ""


class NotionClient:
    def __init__(
        self,
        *,
        token: str,
        api_base: str = NOTION_API_BASE,
        notion_version: str = NOTION_API_VERSION,
        session: requests.Session | None = None,
    ):
        self.api_base = api_base.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": notion_version,
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        response = self.session.request(method, f"{self.api_base}{path}", timeout=30, **kwargs)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        raise NotionSyncError("Unexpected Notion API response")

    def get_page(self, page_id: str) -> dict[str, Any]:
        return self._request("GET", f"/pages/{page_id}")

    def get_page_markdown(self, page_id: str) -> str:
        payload = self._request("GET", f"/pages/{page_id}/markdown")
        return _extract_markdown(payload).strip()

    def get_workspace_name(self) -> str | None:
        payload = self._request("GET", "/users/me")
        bot = payload.get("bot")
        owner = bot.get("owner") if isinstance(bot, dict) else None
        workspace_name = owner.get("workspace_name") if isinstance(owner, dict) else None
        return workspace_name or payload.get("name")

    def iter_child_page_ids(self, block_id: str) -> Iterable[str]:
        cursor: str | None = None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            payload = self._request("GET", f"/blocks/{block_id}/children", params=params)
            for block in payload.get("results", []):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "child_page" and block.get("id"):
                    yield block["id"]
            cursor = payload.get("next_cursor")
            if not payload.get("has_more"):
                break

    def collect_page_tree(self, root_page_id: str) -> list[NotionPage]:
        pages: list[NotionPage] = []

        def walk(page_id: str, parent_page_id: str | None) -> None:
            page = self.get_page(page_id)
            markdown = self.get_page_markdown(page_id)
            pages.append(
                NotionPage(
                    page_id=page_id,
                    title=_extract_title(page),
                    url=page.get("url"),
                    last_edited_time=page.get("last_edited_time"),
                    parent_page_id=parent_page_id,
                    markdown=markdown,
                )
            )
            for child_id in self.iter_child_page_ids(page_id):
                walk(child_id, page_id)

        walk(root_page_id, None)
        return pages


def _get_connector(db: Session, connector_id: str = "notion") -> Connector:
    connector = db.query(Connector).filter(Connector.id == connector_id).first()
    if not connector:
        raise NotionSyncError(f"Connector {connector_id} not found")
    return connector


def get_configured_roots(connector: Connector) -> list[NotionRoot]:
    config = connector.config_json or {}
    configured = config.get("root_pages") if isinstance(config, dict) else None
    roots: list[NotionRoot] = []
    if isinstance(configured, list):
        for item in configured:
            if not isinstance(item, dict) or not item.get("page_id"):
                continue
            roots.append(
                NotionRoot(
                    page_id=item["page_id"],
                    page_url=item.get("page_url"),
                )
            )

    if not roots and connector.root_page_id:
        roots.append(
            NotionRoot(
                page_id=connector.root_page_id,
                page_url=connector.root_page_url,
            )
        )
    return roots


def configure_notion_connector(
    db: Session,
    *,
    root_pages: list[str],
    connector_id: str = "notion",
) -> Connector:
    connector = _get_connector(db, connector_id)
    roots = normalize_notion_roots(root_pages)
    primary_root = roots[0]

    connector.provider = "notion"
    connector.root_page_id = primary_root.page_id
    connector.root_page_url = primary_root.page_url
    connector.status = ConnectorStatus.CONNECTED
    connector.last_sync_error = None
    connector.config_json = {
        **(connector.config_json or {}),
        "root_pages": [
            {
                "page_id": root.page_id,
                "page_url": root.page_url,
            }
            for root in roots
        ],
    }
    db.add(connector)
    db.commit()
    db.refresh(connector)
    return connector


def queue_notion_sync(db: Session, connector_id: str = "notion") -> Connector:
    connector = _get_connector(db, connector_id)
    if not get_configured_roots(connector):
        raise NotionSyncError("Notion connector is not configured with any root pages")

    connector.last_sync_status = ConnectorSyncStatus.SYNCING
    connector.last_sync_error = None
    db.add(connector)
    db.commit()
    db.refresh(connector)
    return connector


def sync_notion_connector(
    db: Session,
    *,
    connector_id: str = "notion",
    client: NotionClient | None = None,
) -> dict[str, Any]:
    connector = _get_connector(db, connector_id)
    try:
        token = os.getenv("NOTION_TOKEN", "").strip()
        if not token:
            raise NotionSyncError("NOTION_TOKEN is not configured")

        roots = get_configured_roots(connector)
        if not roots:
            raise NotionSyncError("Notion connector is missing root pages")

        notion = client or NotionClient(token=token)
        synced_documents: set[str] = set()
        inserted_chunks = 0
        workspace_name = notion.get_workspace_name()
        pages_by_id: dict[str, tuple[NotionPage, str]] = {}
        for root in roots:
            for page in notion.collect_page_tree(root.page_id):
                pages_by_id.setdefault(page.page_id, (page, root.page_id))

        for page, root_page_id in pages_by_id.values():
            if not page.markdown.strip():
                continue
            source_document = page.page_id
            synced_documents.add(source_document)
            inserted_chunks += upsert_markdown_document(
                db,
                source_document=source_document,
                source="notion",
                source_uri=page.url,
                content=page.markdown,
                tags=["notion"],
                extra_metadata={
                    "page_id": page.page_id,
                    "parent_page_id": page.parent_page_id,
                    "root_page_id": root_page_id,
                    "last_edited_time": page.last_edited_time,
                    "title": page.title,
                    "connector_id": connector.id,
                },
            )

        existing_documents = {
            chunk.source_document
            for chunk in db.query(RunbookChunk)
            .filter(RunbookChunk.source == "notion")
            .all()
            if isinstance(chunk.doc_metadata, dict) and chunk.doc_metadata.get("connector_id") == connector.id
        }
        stale_documents = existing_documents - synced_documents
        deleted_chunks = delete_source_documents(
            db,
            source="notion",
            source_documents=stale_documents,
        )

        connector.provider = "notion"
        connector.status = ConnectorStatus.CONNECTED
        connector.workspace_name = workspace_name
        connector.last_synced_at = utcnow()
        connector.last_sync_status = ConnectorSyncStatus.SUCCEEDED
        connector.last_sync_error = None
        connector.metadata_json = {
            **(connector.metadata_json or {}),
            "configured_root_pages": [
                {"page_id": root.page_id, "page_url": root.page_url}
                for root in roots
            ],
            "synced_page_count": len(synced_documents),
            "inserted_chunk_count": inserted_chunks,
            "deleted_chunk_count": deleted_chunks,
        }
        db.add(connector)
        db.commit()
        db.refresh(connector)
        return {
            "status": "success",
            "synced_pages": len(synced_documents),
            "inserted_chunks": inserted_chunks,
            "deleted_chunks": deleted_chunks,
        }
    except Exception as exc:
        db.rollback()
        connector = _get_connector(db, connector_id)
        connector.last_sync_status = ConnectorSyncStatus.FAILED
        connector.last_sync_error = str(exc)
        db.add(connector)
        db.commit()
        raise


def list_synced_notion_pages(
    db: Session,
    *,
    connector_id: str = "notion",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    pages: dict[str, dict[str, Any]] = {}
    chunks = (
        db.query(RunbookChunk)
        .filter(RunbookChunk.source == "notion")
        .order_by(RunbookChunk.source_document.asc(), RunbookChunk.chunk_index.asc())
        .all()
    )
    for chunk in chunks:
        metadata = chunk.doc_metadata or {}
        if metadata.get("connector_id") != connector_id:
            continue
        page_id = metadata.get("page_id") or chunk.source_document
        entry = pages.get(page_id)
        if not entry:
            pages[page_id] = {
                "page_id": page_id,
                "title": chunk.title or metadata.get("title") or chunk.source_document,
                "page_url": chunk.source_uri,
                "root_page_id": metadata.get("root_page_id"),
                "last_edited_time": metadata.get("last_edited_time"),
                "chunk_count": 1,
            }
        else:
            entry["chunk_count"] += 1

    items = sorted(pages.values(), key=lambda item: ((item.get("title") or "").lower(), item["page_id"]))
    return {
        "items": items[offset: offset + limit],
        "total": len(items),
        "limit": limit,
        "offset": offset,
    }
