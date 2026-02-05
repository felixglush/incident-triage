from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Incident, Alert, IncidentStatus, SeverityLevel

router = APIRouter()


@router.get("/metrics")
def get_dashboard_metrics(db: Session = Depends(get_db)):
    active_incidents = (
        db.query(func.count(Incident.id))
        .filter(~Incident.status.in_([IncidentStatus.RESOLVED, IncidentStatus.CLOSED]))
        .scalar()
        or 0
    )

    critical_incidents = (
        db.query(func.count(Incident.id))
        .filter(Incident.severity == SeverityLevel.CRITICAL)
        .filter(~Incident.status.in_([IncidentStatus.RESOLVED, IncidentStatus.CLOSED]))
        .scalar()
        or 0
    )

    untriaged_alerts = (
        db.query(func.count(Alert.id))
        .filter(Alert.incident_id.is_(None))
        .scalar()
        or 0
    )

    ack_seconds = case(
        (Incident.time_to_acknowledge.isnot(None), Incident.time_to_acknowledge),
        else_=None,
    )
    resolve_seconds = case(
        (Incident.time_to_resolve.isnot(None), Incident.time_to_resolve),
        else_=func.extract(
            "epoch",
            func.coalesce(Incident.closed_at, Incident.resolved_at) - Incident.created_at,
        ),
    )

    mtta_seconds = (
        db.query(func.avg(ack_seconds))
        .filter(Incident.time_to_acknowledge.isnot(None))
        .scalar()
    )

    mttr_seconds = (
        db.query(func.avg(resolve_seconds))
        .filter(func.coalesce(Incident.closed_at, Incident.resolved_at).isnot(None))
        .scalar()
    )

    mtta_minutes = round(float(mtta_seconds) / 60.0) if mtta_seconds else None
    mttr_minutes = round(float(mttr_seconds) / 60.0) if mttr_seconds else None

    return {
        "active_incidents": int(active_incidents),
        "critical_incidents": int(critical_incidents),
        "untriaged_alerts": int(untriaged_alerts),
        "mtta_minutes": mtta_minutes,
        "mttr_minutes": mttr_minutes,
    }
