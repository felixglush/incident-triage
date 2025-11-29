"""
Factory Boy factories for generating test data.

Provides factories for:
- Alert model
- Incident model
- IncidentAction model

Usage:
    # Create a single alert
    alert = AlertFactory()

    # Create multiple alerts
    alerts = AlertFactory.create_batch(10)

    # Override specific fields
    alert = AlertFactory(severity="critical", source="sentry")
"""

from datetime import datetime, timezone

import factory
from factory.alchemy import SQLAlchemyModelFactory

from app.models import Alert, Incident, IncidentAction
from app.models import ActionType, IncidentStatus, SeverityLevel


class AlertFactory(SQLAlchemyModelFactory):
    """Factory for creating Alert instances."""

    class Meta:
        model = Alert
        sqlalchemy_session_persistence = "flush"

    # Required fields
    external_id = factory.Sequence(lambda n: f"test-alert-{n}")
    source = factory.Iterator(["datadog", "sentry", "pagerduty"])
    title = factory.Faker("sentence", nb_words=6)
    message = factory.Faker("text", max_nb_chars=200)

    # Timestamps
    alert_timestamp = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))

    # JSONB payload
    raw_payload = factory.LazyAttribute(
        lambda obj: {
            "id": obj.external_id,
            "title": obj.title,
            "body": obj.message,
            "source": obj.source,
        }
    )

    # ML Classification fields (can be None initially)
    severity = factory.Iterator(
        [
            SeverityLevel.INFO,
            SeverityLevel.WARNING,
            SeverityLevel.ERROR,
            SeverityLevel.CRITICAL,
        ]
    )
    predicted_team = factory.Iterator(["backend", "frontend", "infra", "data"])
    confidence_score = factory.Faker("pyfloat", left_digits=0, right_digits=2, min_value=0.5, max_value=0.99)

    # Extracted entities (can be None)
    service_name = factory.Iterator(["api-service", "web-service", "worker-service", None])
    environment = factory.Iterator(["production", "staging", "development", None])
    region = factory.Iterator(["us-east-1", "us-west-2", "eu-west-1", None])
    error_code = None

    # Relationships (incident_id is set when grouping)
    incident_id = None
    deleted_at = None


class IncidentFactory(SQLAlchemyModelFactory):
    """Factory for creating Incident instances."""

    class Meta:
        model = Incident
        sqlalchemy_session_persistence = "flush"

    title = factory.Faker("sentence", nb_words=8)
    severity = factory.Iterator(
        [
            SeverityLevel.INFO,
            SeverityLevel.WARNING,
            SeverityLevel.ERROR,
            SeverityLevel.CRITICAL,
        ]
    )
    assigned_team = factory.Iterator(["backend", "frontend", "infra", "data"])
    status = factory.Iterator(
        [
            IncidentStatus.OPEN,
            IncidentStatus.INVESTIGATING,
            IncidentStatus.RESOLVED,
        ]
    )

    affected_services = factory.LazyFunction(
        lambda: ["api-service", "database"]
    )

    summary = None  # ML-generated, can be None initially
    root_cause = None
    resolution_notes = None

    created_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    updated_at = factory.LazyFunction(lambda: datetime.now(timezone.utc))
    resolved_at = None


class IncidentActionFactory(SQLAlchemyModelFactory):
    """Factory for creating IncidentAction instances."""

    class Meta:
        model = IncidentAction
        sqlalchemy_session_persistence = "flush"

    incident_id = factory.LazyAttribute(lambda obj: IncidentFactory().id)
    action_type = factory.Iterator(
        [
            ActionType.STATUS_CHANGE,
            ActionType.ASSIGNMENT,
            ActionType.COMMENT,
            ActionType.ALERT_ADDED,
        ]
    )
    description = factory.Faker("sentence", nb_words=10)
    user = factory.Iterator(["system", "john.doe", "jane.smith", "on-call-engineer"])
    timestamp = factory.LazyFunction(lambda: datetime.now(timezone.utc))


# Helper function to setup factories with a database session
def configure_factories(session):
    """
    Configure factories to use a specific database session.

    Call this in your test fixtures to associate factories with the test database session:

    Usage:
        def test_with_factories(db_session):
            configure_factories(db_session)
            alert = AlertFactory()
            # alert is now in the test database
    """
    AlertFactory._meta.sqlalchemy_session = session
    IncidentFactory._meta.sqlalchemy_session = session
    IncidentActionFactory._meta.sqlalchemy_session = session
