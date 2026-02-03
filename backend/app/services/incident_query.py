"""
Query helpers for incidents and alerts.

Centralizes filtering/pagination logic so endpoints stay thin.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Query, Session

from app.models import Alert, Incident, IncidentStatus, SeverityLevel


DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def clamp_limit(limit: Optional[int]) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(int(limit), MAX_LIMIT))


def apply_incident_filters(
    query: Query,
    db: Session,
    status: Optional[IncidentStatus] = None,
    severity: Optional[SeverityLevel] = None,
    service: Optional[str] = None,
    team: Optional[str] = None,
    source: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    updated_from: Optional[datetime] = None,
    updated_to: Optional[datetime] = None,
) -> Query:
    if status is not None:
        query = query.filter(Incident.status == status)
    if severity is not None:
        query = query.filter(Incident.severity == severity)
    if team:
        query = query.filter(Incident.assigned_team == team)

    if created_from is not None:
        query = query.filter(Incident.created_at >= created_from)
    if created_to is not None:
        query = query.filter(Incident.created_at <= created_to)
    if updated_from is not None:
        query = query.filter(Incident.updated_at >= updated_from)
    if updated_to is not None:
        query = query.filter(Incident.updated_at <= updated_to)

    # Filters that rely on Alert table (use EXISTS to avoid breaking aggregates)
    if source:
        query = query.filter(
            db.query(Alert.id)
            .filter(Alert.incident_id == Incident.id, Alert.source == source)
            .exists()
        )

    if service:
        query = query.filter(
            or_(
                Incident.affected_services.contains([service]),
                db.query(Alert.id)
                .filter(Alert.incident_id == Incident.id, Alert.service_name == service)
                .exists(),
            )
        )

    return query


def apply_alert_filters(
    query: Query,
    source: Optional[str] = None,
    severity: Optional[SeverityLevel] = None,
    service: Optional[str] = None,
    environment: Optional[str] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    incident_id: Optional[int] = None,
) -> Query:
    if source:
        query = query.filter(Alert.source == source)
    if severity is not None:
        query = query.filter(Alert.severity == severity)
    if service:
        query = query.filter(Alert.service_name == service)
    if environment:
        query = query.filter(Alert.environment == environment)
    if incident_id is not None:
        query = query.filter(Alert.incident_id == incident_id)
    if created_from is not None:
        query = query.filter(Alert.created_at >= created_from)
    if created_to is not None:
        query = query.filter(Alert.created_at <= created_to)

    return query


def incident_aggregates_subquery(db: Session):
    return (
        db.query(
            Alert.incident_id.label("incident_id"),
            func.count(Alert.id).label("alert_count"),
            func.max(Alert.alert_timestamp).label("last_alert_at"),
        )
        .group_by(Alert.incident_id)
        .subquery()
    )
