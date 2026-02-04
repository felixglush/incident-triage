from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Connector, ConnectorStatus

router = APIRouter()


def serialize_connector(connector: Connector) -> dict:
    return {
        "id": connector.id,
        "name": connector.name,
        "status": connector.status.value,
        "detail": connector.detail,
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
