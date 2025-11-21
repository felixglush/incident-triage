"""
Celery task implementations for OpsRelay.

This module defines background tasks that are executed by Celery workers.
Key responsibilities:
- Alert classification (stub for Phase 1, real ML in Phase 2)
- Entity extraction (stub for Phase 1, real NER in Phase 2)
- Alert grouping into incidents
- Incident metadata management
"""
import logging
from datetime import datetime, timedelta, timezone

from app.workers.celery_app import celery_app
from app.database import SessionLocal
from app.models.database import Alert, Incident, IncidentAction, SeverityLevel, IncidentStatus, ActionType

logger = logging.getLogger(__name__)


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

        # Phase 1: Stub classification
        # In Phase 2, this will call ML inference service for real classification
        alert.severity = SeverityLevel.WARNING
        alert.predicted_team = "backend"
        alert.confidence_score = 0.75

        # Phase 1: Stub entity extraction
        # In Phase 2, this will call NER model for entity extraction
        alert.service_name = "api-service"
        alert.environment = "production"
        alert.region = "us-east-1"

        db.commit()
        logger.debug(f"Alert {alert_id} classified: severity={alert.severity}, team={alert.predicted_team}")

        # Group alert into incident
        incident_id = group_alerts_into_incidents(db, alert)

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
