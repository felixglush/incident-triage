"""
Celery task implementations for OpsRelay.

This module defines background tasks that are executed by Celery workers.
Key responsibilities:
- Alert classification using ML inference service
- Entity extraction using NER models
- Alert grouping into incidents
- Incident metadata management
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy.orm.attributes import flag_modified

from app.workers.celery_app import celery_app
from app.database import SessionLocal
from app.models.database import Alert, Incident, IncidentAction, SeverityLevel, IncidentStatus, ActionType
from app.services.incident_similarity import ensure_incident_embedding

logger = logging.getLogger(__name__)

# ML service URL from environment
ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://localhost:8001")


@celery_app.task(bind=True, max_retries=3)
def process_alert(self, alert_id: int):
    """
    Process an alert through the ML pipeline.

    This task:
    1. Loads the alert from database
    2. Runs classification (stub values for Phase 1)
    3. Runs entity extraction (stub values for Phase 1)
    4. Groups alert into incident
    5. Updates database

    Args:
        alert_id: Primary key of Alert record

    Returns:
        dict: Task result with status and incident_id

    Raises:
        Retries up to 3 times if database is temporarily unavailable
    """
    db = SessionLocal()

    try:
        # Load alert from database
        alert = db.query(Alert).filter(Alert.id == alert_id).first()

        if not alert:
            logger.error(f"Alert {alert_id} not found in database")
            return {"status": "failed", "error": "Alert not found"}

        logger.info(f"Processing alert {alert_id}: {alert.title}")

        # Prepare text for ML classification (combine title + message)
        text = f"{alert.title}. {alert.message or ''}"

        # Call ML service for classification with defensive error handling
        try:
            response = requests.post(
                f"{ML_SERVICE_URL}/classify",
                json={"text": text},
                timeout=5  # 5 second timeout to prevent worker hanging
            )
            response.raise_for_status()
            classification = response.json()

            # Map ML service response to database enums
            severity_str = classification["severity"].upper()
            alert.severity = SeverityLevel[severity_str]
            alert.predicted_team = classification["team"]
            alert.confidence_score = classification["confidence"]
            alert.classification_source = "rule"

            logger.info(
                f"ML classification: severity={severity_str}, team={classification['team']}, "
                f"confidence={classification['confidence']:.2f}"
            )

        except (requests.RequestException, KeyError, ValueError) as e:
            logger.error(f"ML classification failed for alert {alert_id}: {str(e)}")
            # Graceful degradation: use safe defaults
            alert.severity = SeverityLevel.WARNING
            alert.predicted_team = "backend"
            alert.confidence_score = 0.0
            alert.classification_source = "fallback_rule"
            logger.warning(f"Using fallback classification for alert {alert_id}")

        # Call ML service for entity extraction
        try:
            response = requests.post(
                f"{ML_SERVICE_URL}/extract-entities",
                json={"text": text},
                timeout=5
            )
            response.raise_for_status()
            entities = response.json()

            alert.service_name = entities.get("service_name")
            alert.environment = entities.get("environment")
            alert.region = entities.get("region")
            alert.error_code = entities.get("error_code")
            alert.entity_source = entities.get("entity_source") or "regex"
            entity_sources = {}
            if alert.service_name:
                entity_sources["service_name"] = "ml"
            if alert.environment:
                entity_sources["environment"] = "ml"
            if alert.region:
                entity_sources["region"] = "ml"
            if alert.error_code:
                entity_sources["error_code"] = "ml"

            logger.debug(f"Extracted entities: {entities}")

            # Fill any missing entity fields from tags and mark provenance
            fallback_fields = _apply_fallback_entities(alert, entity_sources)
            if fallback_fields:
                entity_sources.update(fallback_fields)
            alert.entity_sources = entity_sources or None
            alert.entity_source = _summarize_entity_source(entity_sources)

        except (requests.RequestException, KeyError) as e:
            logger.error(f"Entity extraction failed for alert {alert_id}: {str(e)}")
            # Fallback: best-effort extraction from raw payload tags
            entity_sources = {}
            fallback_fields = _apply_fallback_entities(alert, entity_sources)
            if fallback_fields:
                entity_sources.update(fallback_fields)
            alert.entity_sources = entity_sources or None
            alert.entity_source = _summarize_entity_source(entity_sources)

        db.commit()
        logger.debug(f"Alert {alert_id} classified: severity={alert.severity}, team={alert.predicted_team}")

        # Group alert into incident
        incident_id = group_alerts_into_incidents(db, alert)

        # Update incident embedding after grouping
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if incident:
            alerts = (
                db.query(Alert)
                .filter(Alert.incident_id == incident.id)
                .order_by(Alert.alert_timestamp.desc())
                .all()
            )
            ensure_incident_embedding(db, incident, alerts)
            db.commit()

        logger.info(f"Alert {alert_id} processed successfully, incident_id={incident_id}")

        return {
            "status": "success",
            "alert_id": alert_id,
            "incident_id": incident_id
        }

    except Exception as e:
        logger.error(f"Error processing alert {alert_id}: {str(e)}", exc_info=True)

        try:
            db.rollback()
        except Exception as rollback_error:
            logger.error(f"Failed to rollback transaction: {rollback_error}")

        # Retry up to 3 times with exponential backoff
        raise self.retry(exc=e, countdown=2 ** self.request.retries)

    finally:
        db.close()


def _apply_fallback_entities(alert: Alert, entity_sources: dict) -> dict:
    """
    Best-effort entity extraction from raw payload when ML service is unavailable.
    """
    payload = alert.raw_payload or {}
    tags = payload.get("tags") or []
    updated = {}

    # Tags usually look like ["service:api", "env:production", "region:us-east-1"]
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, str):
                continue
            if tag.startswith("service:") and not alert.service_name:
                alert.service_name = tag.split(":", 1)[1]
                updated["service_name"] = "tags"
            elif tag.startswith("env:") and not alert.environment:
                alert.environment = tag.split(":", 1)[1]
                updated["environment"] = "tags"
            elif tag.startswith("region:") and not alert.region:
                alert.region = tag.split(":", 1)[1]
                updated["region"] = "tags"
            elif tag.startswith("error:") and not alert.error_code:
                alert.error_code = tag.split(":", 1)[1]
                updated["error_code"] = "tags"

    # If no tags, try minimal inference from title
    if not alert.service_name and alert.title:
        lowered = alert.title.lower()
        for candidate in ["api", "db", "cache", "queue", "worker"]:
            if candidate in lowered:
                alert.service_name = candidate
                updated["service_name"] = "title"
                break

    return updated

def _summarize_entity_source(entity_sources: dict) -> str:
    if not entity_sources:
        return "unknown"
    unique_sources = set(entity_sources.values())
    if len(unique_sources) == 1:
        return unique_sources.pop()
    return "mixed"

def group_alerts_into_incidents(db, alert: Alert) -> int:
    """
    Group alert into incident based on time window and similarity.

    Phase 1 Logic:
    - Simple time-window based grouping (5 minutes)
    - Finds recent open incidents
    - Adds alert to most recent incident OR creates new one

    Phase 2 will replace with:
    - ML-based similarity using embeddings
    - More sophisticated grouping rules

    Args:
        db: SQLAlchemy session
        alert: Alert instance to group

    Returns:
        int: Incident ID (created or matched)

    Algorithm:
    1. Look back 5 minutes from alert timestamp
    2. Find incidents with status = OPEN or INVESTIGATING
    3. If found: add to most recent incident
    4. If not found: create new incident
    """
    try:
        # Calculate time window (5 minutes before alert)
        time_window = alert.alert_timestamp - timedelta(minutes=5)

        logger.debug(f"Looking for incidents between {time_window} and {alert.alert_timestamp}")

        # Find recent open incidents within time window
        recent_incidents = db.query(Incident).filter(
            Incident.status.in_([IncidentStatus.OPEN, IncidentStatus.INVESTIGATING]),
            Incident.created_at >= time_window
        ).order_by(Incident.created_at.desc()).all()

        if recent_incidents:
            # Add alert to most recent incident
            incident = recent_incidents[0]
            alert.incident_id = incident.id
            incident.updated_at = datetime.now(timezone.utc)

            # Add service to affected_services if not already present
            if incident.affected_services is None:
                incident.affected_services = []

            if alert.service_name and alert.service_name not in incident.affected_services:
                incident.affected_services.append(alert.service_name)
                # Mark JSONB field as modified so SQLAlchemy detects the change
                flag_modified(incident, "affected_services")

            db.commit()

            logger.info(
                f"Alert {alert.id} added to existing incident {incident.id} "
                f"(created {incident.created_at})"
            )

            # Log action in incident timeline
            action = IncidentAction(
                incident_id=incident.id,
                action_type=ActionType.ALERT_ADDED,
                description=f"Alert {alert.external_id} ({alert.title}) grouped into incident",
                user="system",
                extra_metadata={
                    "alert_id": alert.id,
                    "source": alert.source,
                    "severity": alert.severity.value if alert.severity else None
                }
            )
            db.add(action)
            db.commit()

            return incident.id

        else:
            # Create new incident
            logger.info(
                f"No recent incidents found, creating new incident for alert {alert.id}"
            )

            incident = Incident(
                title=alert.title,
                severity=alert.severity or SeverityLevel.WARNING,
                assigned_team=alert.predicted_team or "unassigned",
                status=IncidentStatus.OPEN,
                affected_services=[alert.service_name] if alert.service_name else []
            )

            db.add(incident)
            db.flush()  # Get incident ID without committing

            # Link alert to incident
            alert.incident_id = incident.id

            db.commit()

            logger.info(
                f"Created new incident {incident.id} for alert {alert.id}"
            )

            # Log action in incident timeline
            action = IncidentAction(
                incident_id=incident.id,
                action_type=ActionType.STATUS_CHANGE,
                description=f"Incident created from alert {alert.external_id}",
                user="system",
                extra_metadata={
                    "trigger": "auto_grouping",
                    "alert_id": alert.id,
                    "alert_count": 1
                }
            )
            db.add(action)
            db.commit()

            return incident.id

    except Exception as e:
        logger.error(f"Error grouping alert {alert.id} into incident: {str(e)}", exc_info=True)
        db.rollback()
        raise
