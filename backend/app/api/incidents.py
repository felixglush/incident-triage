"""
Incident API endpoints for reviewing and updating incidents.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Incident, IncidentAction, IncidentStatus, SeverityLevel, ActionType, Alert
from app.services.incident_query import (
    apply_incident_filters,
    clamp_limit,
    incident_aggregates_subquery,
)
from app.services.incident_similarity import find_similar_incidents
from app.services.incident_summaries import summarize_incident

router = APIRouter()


ALLOWED_TRANSITIONS = {
    IncidentStatus.OPEN: {IncidentStatus.INVESTIGATING},
    IncidentStatus.INVESTIGATING: {IncidentStatus.RESOLVED},
    IncidentStatus.RESOLVED: {IncidentStatus.CLOSED},
    IncidentStatus.CLOSED: set(),
}


def serialize_incident(incident: Incident, alert_count: Optional[int], last_alert_at: Optional[datetime]):
    return {
        "id": incident.id,
        "title": incident.title,
        "status": incident.status.value,
        "severity": incident.severity.value,
        "assigned_team": incident.assigned_team,
        "assigned_user": incident.assigned_user,
        "summary": incident.summary,
        "summary_citations": incident.summary_citations,
        "next_steps": incident.next_steps,
        "affected_services": incident.affected_services or [],
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
        "updated_at": incident.updated_at.isoformat() if incident.updated_at else None,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "closed_at": incident.closed_at.isoformat() if incident.closed_at else None,
        "alert_count": int(alert_count or 0),
        "last_alert_at": last_alert_at.isoformat() if last_alert_at else None,
    }


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
        "incident_id": alert.incident_id,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }


def serialize_action(action: IncidentAction):
    return {
        "id": action.id,
        "action_type": action.action_type.value,
        "description": action.description,
        "user": action.user,
        "extra_metadata": action.extra_metadata,
        "timestamp": action.timestamp.isoformat() if action.timestamp else None,
    }


@router.get("")
def list_incidents(
    status: Optional[IncidentStatus] = None,
    severity: Optional[SeverityLevel] = None,
    service: Optional[str] = None,
    team: Optional[str] = None,
    source: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    updated_from: Optional[datetime] = None,
    updated_to: Optional[datetime] = None,
    limit: Optional[int] = None,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    limit = clamp_limit(limit)

    aggregates = incident_aggregates_subquery(db)

    base_query = db.query(Incident)
    base_query = apply_incident_filters(
        base_query,
        db,
        status=status,
        severity=severity,
        service=service,
        team=team,
        source=source,
        created_from=created_from,
        created_to=created_to,
        updated_from=updated_from,
        updated_to=updated_to,
    )

    total = base_query.count()

    query = (
        db.query(Incident, aggregates.c.alert_count, aggregates.c.last_alert_at)
        .outerjoin(aggregates, Incident.id == aggregates.c.incident_id)
    )

    query = apply_incident_filters(
        query,
        db,
        status=status,
        severity=severity,
        service=service,
        team=team,
        source=source,
        created_from=created_from,
        created_to=created_to,
        updated_from=updated_from,
        updated_to=updated_to,
    )

    items = (
        query.order_by(Incident.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    results = [serialize_incident(incident, alert_count, last_alert_at) for incident, alert_count, last_alert_at in items]

    return {
        "items": results,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{incident_id}")
def get_incident(incident_id: int, db: Session = Depends(get_db)):
    aggregates = incident_aggregates_subquery(db)

    row = (
        db.query(Incident, aggregates.c.alert_count, aggregates.c.last_alert_at)
        .outerjoin(aggregates, Incident.id == aggregates.c.incident_id)
        .filter(Incident.id == incident_id)
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Incident not found")

    incident, alert_count, last_alert_at = row

    alerts = (
        db.query(Alert)
        .filter(Alert.incident_id == incident.id)
        .order_by(Alert.alert_timestamp.desc())
        .all()
    )

    actions = (
        db.query(IncidentAction)
        .filter(IncidentAction.incident_id == incident.id)
        .order_by(IncidentAction.timestamp.desc())
        .all()
    )

    return {
        "incident": serialize_incident(incident, alert_count, last_alert_at),
        "alerts": [serialize_alert(alert) for alert in alerts],
        "actions": [serialize_action(action) for action in actions],
    }


@router.get("/{incident_id}/similar")
def get_similar_incidents(
    incident_id: int,
    limit: int = 5,
    min_score: float = 0.1,
    db: Session = Depends(get_db),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    alerts = (
        db.query(Alert)
        .filter(Alert.incident_id == incident.id)
        .order_by(Alert.alert_timestamp.desc())
        .all()
    )

    matches = find_similar_incidents(db, incident, alerts, limit=limit, min_score=min_score)

    items = []
    for item in matches:
        match = item["incident"]
        items.append({
            "id": match.id,
            "title": match.title,
            "status": match.status.value,
            "severity": match.severity.value,
            "assigned_team": match.assigned_team,
            "score": round(item["score"], 3),
        })

    return {
        "items": items,
        "total": len(items),
        "limit": limit,
    }


@router.post("/{incident_id}/summarize")
def summarize_incident_endpoint(
    incident_id: int,
    limit_similar: int = 5,
    limit_runbook: int = 5,
    force: bool = False,
    db: Session = Depends(get_db),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    if incident.summary and incident.next_steps and not force:
        aggregates = incident_aggregates_subquery(db)
        row = (
            db.query(Incident, aggregates.c.alert_count, aggregates.c.last_alert_at)
            .outerjoin(aggregates, Incident.id == aggregates.c.incident_id)
            .filter(Incident.id == incident.id)
            .first()
        )
        incident_row, alert_count, last_alert_at = row
        return {
            "incident": serialize_incident(incident_row, alert_count, last_alert_at),
            "summary": incident_row.summary,
            "citations": incident_row.summary_citations or [],
            "next_steps": incident_row.next_steps or [],
            "cached": True,
        }

    try:
        result = summarize_incident(
            db,
            incident_id,
            limit_similar=limit_similar,
            limit_runbook=limit_runbook,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    aggregates = incident_aggregates_subquery(db)
    row = (
        db.query(Incident, aggregates.c.alert_count, aggregates.c.last_alert_at)
        .outerjoin(aggregates, Incident.id == aggregates.c.incident_id)
        .filter(Incident.id == incident_id)
        .first()
    )
    incident_row, alert_count, last_alert_at = row

    return {
        "incident": serialize_incident(incident_row, alert_count, last_alert_at),
        "summary": result["summary"],
        "citations": result["citations"],
        "next_steps": result["next_steps"],
        "cached": False,
    }


@router.patch("/{incident_id}/status")
def update_incident_status(
    incident_id: int,
    status: IncidentStatus,
    db: Session = Depends(get_db),
):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    if incident.status == status:
        return {"status": "no_change", "incident_id": incident.id}

    allowed = ALLOWED_TRANSITIONS.get(incident.status, set())
    if status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition from {incident.status.value} to {status.value}",
        )

    previous = incident.status
    incident.status = status

    if status == IncidentStatus.RESOLVED:
        incident.resolved_at = datetime.utcnow()
    if status == IncidentStatus.CLOSED:
        incident.closed_at = datetime.utcnow()

    db.add(incident)
    db.flush()

    action = IncidentAction(
        incident_id=incident.id,
        action_type=ActionType.STATUS_CHANGE,
        description=f"Status changed from {previous.value} to {status.value}",
        user="system",
        extra_metadata={"from": previous.value, "to": status.value},
    )
    db.add(action)
    db.commit()

    return {"status": "updated", "incident_id": incident.id, "new_status": status.value}
