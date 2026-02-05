"""
Webhook processing business logic.

Handles parsing of different webhook formats and creating Alert records.
Separates business logic from API endpoint handlers.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models.database import Alert, SeverityLevel

logger = logging.getLogger(__name__)


class WebhookProcessor:
    """Processes webhooks from different monitoring platforms"""

    def __init__(self, db: Session):
        self.db = db

    def process_datadog_webhook(self, payload: Dict[str, Any]) -> Alert:
        """
        Process a Datadog webhook and create an Alert.

        Datadog webhook format:
        {
            "id": "12345",
            "title": "High CPU usage",
            "body": "CPU > 80% for 5 minutes",
            "priority": "normal|high|critical",
            "last_updated": "2024-01-01T12:00:00Z",
            "tags": ["service:api", "env:production"],
            ...
        }

        Args:
            payload: Parsed JSON webhook payload

        Returns:
            Created Alert object

        Raises:
            ValueError: If required fields are missing
        """
        # Parse Datadog-specific fields
        alert_data = self._parse_datadog_alert(payload)

        # Check for duplicates using external_id
        existing = self.db.query(Alert).filter(
            Alert.source == "datadog",
            Alert.external_id == alert_data["external_id"]
        ).first()

        if existing:
            logger.info(f"Duplicate Datadog alert: {alert_data['external_id']}")
            return existing

        # Create new alert
        alert = Alert(
            external_id=alert_data["external_id"],
            source="datadog",
            title=alert_data["title"],
            message=alert_data["message"],
            raw_payload=payload,
            alert_timestamp=alert_data["timestamp"],
            # ML fields populated later by Celery worker
            severity=None,
            predicted_team=None,
            confidence_score=None,
        )

        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)
        # Avoid stale identity map when async processing updates this alert
        self.db.expire(alert)

        logger.info(f"Created alert {alert.id} from Datadog: {alert.title}")
        return alert

    def process_sentry_webhook(self, payload: Dict[str, Any]) -> Alert:
        """
        Process a Sentry webhook and create an Alert.

        Sentry webhook format:
        {
            "id": "abc123",
            "project": "my-app",
            "message": "ZeroDivisionError: division by zero",
            "culprit": "app.views.index",
            "level": "error",
            "timestamp": "2024-01-01T12:00:00.000000Z",
            "tags": [...],
            ...
        }

        Args:
            payload: Parsed JSON webhook payload

        Returns:
            Created Alert object

        Raises:
            ValueError: If required fields are missing
        """
        # Parse Sentry-specific fields
        alert_data = self._parse_sentry_alert(payload)

        # Check for duplicates
        existing = self.db.query(Alert).filter(
            Alert.source == "sentry",
            Alert.external_id == alert_data["external_id"]
        ).first()

        if existing:
            logger.info(f"Duplicate Sentry alert: {alert_data['external_id']}")
            return existing

        # Create new alert
        alert = Alert(
            external_id=alert_data["external_id"],
            source="sentry",
            title=alert_data["title"],
            message=alert_data["message"],
            raw_payload=payload,
            alert_timestamp=alert_data["timestamp"],
        )

        self.db.add(alert)
        self.db.commit()
        self.db.refresh(alert)
        # Avoid stale identity map when async processing updates this alert
        self.db.expire(alert)

        logger.info(f"Created alert {alert.id} from Sentry: {alert.title}")
        return alert

    def _parse_datadog_alert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract standardized alert data from Datadog payload.

        Args:
            payload: Raw Datadog webhook payload

        Returns:
            Dict with standardized fields: external_id, title, message, timestamp

        Raises:
            ValueError: If required fields are missing
        """
        try:
            # Extract required fields
            external_id = payload.get("id")
            if not external_id:
                raise ValueError("Missing 'id' field in Datadog payload")

            title = payload.get("title", "Datadog Alert")
            message = payload.get("body", "")

            # Parse timestamp
            timestamp_str = payload.get("last_updated")
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                except ValueError:
                    logger.warning(f"Invalid timestamp format: {timestamp_str}")
                    timestamp = datetime.now(timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)

            # Extract tags for additional context (stored in raw_payload)
            tags = payload.get("tags", [])

            return {
                "external_id": str(external_id),
                "title": title[:500],  # Truncate to DB limit
                "message": message,
                "timestamp": timestamp,
                "tags": tags
            }

        except KeyError as e:
            raise ValueError(f"Missing required field in Datadog payload: {e}")

    def _parse_sentry_alert(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract standardized alert data from Sentry payload.

        Args:
            payload: Raw Sentry webhook payload

        Returns:
            Dict with standardized fields: external_id, title, message, timestamp

        Raises:
            ValueError: If required fields are missing
        """
        try:
            # Sentry can send different event types - handle accordingly
            # For issue alerts, the structure is nested
            if "data" in payload and "issue" in payload["data"]:
                issue = payload["data"]["issue"]
                event = payload["data"].get("event", {})

                external_id = issue.get("id")
                title = issue.get("title", "Sentry Issue")
                message = event.get("message", issue.get("metadata", {}).get("value", ""))
                timestamp_str = event.get("timestamp") or issue.get("lastSeen")
            else:
                # Direct event format
                external_id = payload.get("id") or payload.get("event_id")
                title = payload.get("title") or payload.get("message", "Sentry Event")
                message = payload.get("message", "")
                timestamp_str = payload.get("timestamp")

            if not external_id:
                raise ValueError("Missing event/issue ID in Sentry payload")

            # Parse timestamp
            if timestamp_str:
                try:
                    # Sentry timestamps are ISO format with microseconds
                    timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                except ValueError:
                    logger.warning(f"Invalid timestamp format: {timestamp_str}")
                    timestamp = datetime.now(timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)

            return {
                "external_id": str(external_id),
                "title": title[:500],
                "message": message,
                "timestamp": timestamp
            }

        except KeyError as e:
            raise ValueError(f"Missing required field in Sentry payload: {e}")
