"""
Alert API endpoints for reviewing alerts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Alert, SeverityLevel
from app.services.incident_query import apply_alert_filters, clamp_limit

router = APIRouter()


def serialize_alert(alert: Alert):
    return {
        "id": alert.id,
        "external_id": alert.external_id,
        "source": alert.source,
        "title": alert.title,
        "message": alert.message,
        "alert_timestamp": alert.alert_timestamp.isoformat() if alert.alert_timestamp else None,
        "severity": alert.severity.value if alert.severity else None,
        "predicted_team": alert.predicted_team,
        "confidence_score": alert.confidence_score,
        "classification_source": alert.classification_source,
        "service_name": alert.service_name,
        "environment": alert.environment,
        "region": alert.region,
        "error_code": alert.error_code,
        "entity_source": alert.entity_source,
        "entity_sources": alert.entity_sources,
        "incident_id": alert.incident_id,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }


@router.get("")
def list_alerts(
    source: Optional[str] = None,
    severity: Optional[SeverityLevel] = None,
    service: Optional[str] = None,
    environment: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    incident_id: Optional[int] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    limit = clamp_limit(limit)

    base_query = db.query(Alert)
    base_query = apply_alert_filters(
        base_query,
        source=source,
        severity=severity,
        service=service,
        environment=environment,
        created_from=created_from,
        created_to=created_to,
        incident_id=incident_id,
    )

    total = base_query.count()

    items = (
        base_query.order_by(Alert.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "items": [serialize_alert(alert) for alert in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
