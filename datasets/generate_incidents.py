#!/usr/bin/env python3
"""
Generate sample incidents + alerts directly in the database.

Usage:
    python datasets/generate_incidents.py --count 10

Requires DATABASE_URL env to be set (or uses default from app.database).
"""
import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure backend is on path for local execution
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import get_db_context
from app.models import Incident, Alert, IncidentAction, IncidentStatus, SeverityLevel, ActionType


SERVICES = ["api", "db", "cache", "queue", "worker"]
SOURCES = ["datadog", "sentry"]
TITLES = [
    "High error rate",
    "Service unavailable",
    "Latency spike",
    "CPU saturation",
    "Database connection issues",
]


def main():
    parser = argparse.ArgumentParser(description="Generate sample incidents + alerts")
    parser.add_argument("--count", type=int, default=10, help="Number of incidents")
    parser.add_argument("--alerts-per-incident", type=int, default=3)
    args = parser.parse_args()

    now = datetime.now(timezone.utc)

    with get_db_context() as db:
        for i in range(args.count):
            title = random.choice(TITLES)
            severity = random.choice(list(SeverityLevel))
            status = random.choice(list(IncidentStatus))
            service = random.choice(SERVICES)

            incident = Incident(
                title=f"{title} ({service})",
                severity=severity,
                status=status,
                assigned_team="backend",
                affected_services=[service],
                created_at=now - timedelta(hours=i),
            )
            db.add(incident)
            db.flush()

            # Log incident creation action
            db.add(
                IncidentAction(
                    incident_id=incident.id,
                    action_type=ActionType.STATUS_CHANGE,
                    description="Incident created from seed data",
                    user="seed",
                    extra_metadata={"seed": True, "status": status.value},
                )
            )

            for j in range(args.alerts_per_incident):
                alert_time = now - timedelta(hours=i, minutes=j * 5)
                alert = Alert(
                    external_id=f"seed-{i}-{j}",
                    source=random.choice(SOURCES),
                    title=f"{title} {j}",
                    message=f"Auto-generated alert for {service}",
                    raw_payload={"seed": True, "incident": i, "alert": j},
                    alert_timestamp=alert_time,
                    service_name=service,
                    environment="production",
                    incident_id=incident.id,
                )
                db.add(alert)

                # Log alert added action
                db.add(
                    IncidentAction(
                        incident_id=incident.id,
                        action_type=ActionType.ALERT_ADDED,
                        description=f"Seed alert {alert.external_id} added to incident",
                        user="seed",
                        extra_metadata={"seed": True, "alert_index": j},
                    )
                )

        db.commit()

    print(f"Seeded {args.count} incidents with {args.alerts_per_incident} alerts each")


if __name__ == "__main__":
    main()
