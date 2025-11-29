"""
Sample webhook payloads for testing.

Contains realistic webhook payloads from different monitoring platforms.
"""

from datetime import datetime, timezone


def get_datadog_alert(alert_id: str = "test-001", **overrides):
    """
    Generate a sample Datadog webhook payload.

    Args:
        alert_id: Unique alert identifier
        **overrides: Override default fields

    Returns:
        Dict representing Datadog webhook payload
    """
    payload = {
        "id": alert_id,
        "title": "High CPU usage detected",
        "body": "CPU utilization has exceeded 80% threshold for 5 minutes on api-service",
        "priority": "warning",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "tags": [
            "service:api-service",
            "env:production",
            "region:us-east-1",
            "alert_type:metric",
        ],
        "host": "api-server-01.example.com",
        "alert_type": "metric alert",
        "org": {
            "id": 12345,
            "name": "Example Org",
        },
    }
    payload.update(overrides)
    return payload


def get_sentry_alert(alert_id: str = "sentry-001", **overrides):
    """
    Generate a sample Sentry webhook payload.

    Args:
        alert_id: Unique issue identifier
        **overrides: Override default fields

    Returns:
        Dict representing Sentry webhook payload
    """
    payload = {
        "id": alert_id,
        "data": {
            "issue": {
                "id": alert_id,
                "title": "TypeError: Cannot read property 'user' of undefined",
                "culprit": "app/components/UserProfile.tsx in render",
                "shortId": "EXAMPLE-1",
                "logger": None,
                "level": "error",
                "status": "unresolved",
                "statusDetails": {},
                "isPublic": False,
                "platform": "javascript",
                "project": {
                    "id": "123456",
                    "name": "web-frontend",
                    "slug": "web-frontend",
                },
                "type": "error",
                "metadata": {
                    "type": "TypeError",
                    "value": "Cannot read property 'user' of undefined",
                },
                "numComments": 0,
                "assignedTo": None,
                "isBookmarked": False,
                "isSubscribed": False,
                "subscriptionDetails": None,
                "hasSeen": False,
                "annotations": [],
                "isUnhandled": True,
                "count": "42",
                "userCount": 12,
                "firstSeen": datetime.now(timezone.utc).isoformat(),
                "lastSeen": datetime.now(timezone.utc).isoformat(),
                "permalink": "https://sentry.io/organizations/example/issues/123456/",
            }
        },
        "action": "created",
    }
    payload.update(overrides)
    return payload


def get_pagerduty_alert(alert_id: str = "pd-001", **overrides):
    """
    Generate a sample PagerDuty webhook payload.

    Args:
        alert_id: Unique incident identifier
        **overrides: Override default fields

    Returns:
        Dict representing PagerDuty webhook payload
    """
    payload = {
        "messages": [
            {
                "id": alert_id,
                "event": "incident.triggered",
                "created_on": datetime.now(timezone.utc).isoformat(),
                "incident": {
                    "id": alert_id,
                    "incident_number": 123,
                    "title": "Service health check failing",
                    "description": "Health check endpoint returning 503 for database-service",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "status": "triggered",
                    "incident_key": f"db-health-check-{alert_id}",
                    "service": {
                        "id": "PSERVICE1",
                        "name": "Database Service",
                        "description": "Primary PostgreSQL database",
                    },
                    "assigned_to_user": None,
                    "trigger_summary_data": {
                        "subject": "Database health check failing",
                        "description": "Repeated 503 responses from /health endpoint",
                    },
                    "urgency": "high",
                },
            }
        ],
    }
    payload.update(overrides)
    return payload


# Test cases with different scenarios
DATADOG_HIGH_CPU = get_datadog_alert(
    alert_id="dd-cpu-001",
    title="High CPU on api-service",
    priority="critical",
    tags=["service:api-service", "env:production", "metric:cpu"],
)

DATADOG_HIGH_MEMORY = get_datadog_alert(
    alert_id="dd-mem-001",
    title="Memory usage critical",
    body="Memory utilization at 95%",
    priority="critical",
    tags=["service:worker-service", "env:production", "metric:memory"],
)

SENTRY_JAVASCRIPT_ERROR = get_sentry_alert(
    alert_id="sentry-js-001",
)

SENTRY_PYTHON_ERROR = get_sentry_alert(
    alert_id="sentry-py-001",
    **{
        "data": {
            "issue": {
                "id": "sentry-py-001",
                "title": "ValueError: Invalid JSON response",
                "platform": "python",
                "culprit": "api.views.process_webhook",
                "metadata": {
                    "type": "ValueError",
                    "value": "Invalid JSON response from upstream service",
                },
                "lastSeen": datetime.now(timezone.utc).isoformat(),
            }
        }
    },
)

PAGERDUTY_DB_DOWN = get_pagerduty_alert(
    alert_id="pd-db-001",
    **{
        "messages": [
            {
                "id": "pd-db-001",
                "incident": {
                    "id": "pd-db-001",
                    "title": "Database connection pool exhausted",
                    "description": "All database connections in use, unable to serve requests",
                    "status": "triggered",
                    "urgency": "high",
                }
            }
        ]
    },
)


# Duplicate detection test cases
DUPLICATE_ALERT_1 = get_datadog_alert(alert_id="dup-test-001", title="First occurrence")
DUPLICATE_ALERT_2 = get_datadog_alert(
    alert_id="dup-test-001", title="Second occurrence (should be detected as duplicate)"
)
