from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Connector, ConnectorStatus
from app.services.notion_connector import (
    NotionSyncError,
    configure_notion_connector,
    get_configured_roots,
    list_synced_notion_pages,
    queue_notion_sync,
)
from app.workers.tasks import sync_notion_connector_task

router = APIRouter()


class NotionConfigureRequest(BaseModel):
    root_pages: Optional[List[str]] = None
    root_page_id: Optional[str] = None
    root_page_url: Optional[str] = None

    @model_validator(mode="after")
    def validate_root_page(self) -> "NotionConfigureRequest":
        roots = [value for value in (self.root_pages or []) if value and value.strip()]
        if not roots:
            if self.root_page_id:
                roots.append(self.root_page_id)
            if self.root_page_url:
                roots.append(self.root_page_url)
        if not roots:
            raise ValueError("At least one root page ID or URL is required")
        self.root_pages = roots
        return self


def serialize_connector(connector: Connector) -> dict:
    roots = [
        {"page_id": root.page_id, "page_url": root.page_url}
        for root in get_configured_roots(connector)
    ]
    return {
        "id": connector.id,
        "name": connector.name,
        "provider": connector.provider,
        "status": connector.status.value,
        "detail": connector.detail,
        "root_pages": roots,
        "workspace_name": connector.workspace_name,
        "last_synced_at": connector.last_synced_at.isoformat() if connector.last_synced_at else None,
        "last_sync_status": connector.last_sync_status.value if connector.last_sync_status else None,
        "last_sync_error": connector.last_sync_error,
        "config": connector.config_json or {},
        "metadata": connector.metadata_json or {},
        "updated_at": connector.updated_at.isoformat() if connector.updated_at else None,
    }


@router.get("")
def list_connectors(limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    total = db.query(Connector).count()
    items = (
        db.query(Connector)
        .order_by(Connector.name.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [serialize_connector(item) for item in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{connector_id}")
def get_connector(connector_id: str, db: Session = Depends(get_db)):
    connector = db.query(Connector).filter(Connector.id == connector_id).first()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    return serialize_connector(connector)


@router.post("/{connector_id}/connect")
def connect_connector(connector_id: str, db: Session = Depends(get_db)):
    connector = db.query(Connector).filter(Connector.id == connector_id).first()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")

    if connector.status == ConnectorStatus.NOT_CONNECTED:
        connector.status = ConnectorStatus.CONNECTED
    db.add(connector)
    db.commit()

    return {
        "status": "updated",
        "connector_id": connector.id,
        "new_status": connector.status.value,
    }


@router.post("/notion/configure")
def configure_notion(request: NotionConfigureRequest, db: Session = Depends(get_db)):
    try:
        connector = configure_notion_connector(
            db,
            root_pages=request.root_pages or [],
        )
    except NotionSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "status": "configured",
        "connector": serialize_connector(connector),
    }


@router.post("/notion/sync")
def sync_notion(db: Session = Depends(get_db)):
    try:
        connector = queue_notion_sync(db)
    except NotionSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = sync_notion_connector_task.delay("notion")

    return {
        "status": "accepted",
        "connector": serialize_connector(connector),
        "task_id": getattr(result, "id", None),
    }


@router.get("/notion/pages")
def get_notion_pages(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return list_synced_notion_pages(
        db,
        connector_id="notion",
        limit=limit,
        offset=offset,
    )
