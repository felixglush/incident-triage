#!/usr/bin/env python3
"""
Database initialization script for OpsRelay.

This script:
1. Tests database connectivity
2. Enables required PostgreSQL extensions
3. Creates all tables with proper indexes
4. Optionally loads seed data

Usage:
    python init_db.py              # Initialize schema only
    python init_db.py --seed       # Initialize with seed data
    python init_db.py --drop --yes # WARNING: Drop and recreate (non-interactive)
"""
import sys
import argparse
import logging
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text
from app.database import init_db, drop_db, check_connection, engine
from app.models.database import (
    Alert, Incident, IncidentAction, RunbookChunk, Connector, ConnectorStatus,
    SeverityLevel, IncidentStatus, ActionType
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def enable_extensions():
    """Enable required PostgreSQL extensions"""
    logger.info("Enabling PostgreSQL extensions...")

    with engine.connect() as conn:
        try:
            # pgvector for embeddings
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            logger.info("✓ pgvector extension enabled")

            # pg_trgm for trigram text search
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            logger.info("✓ pg_trgm extension enabled")

            conn.commit()

        except Exception as e:
            logger.error(f"Error enabling extensions: {e}")
            logger.warning("Continuing without extensions...")
            conn.rollback()


def load_runbooks_from_file(db, path: Path) -> int:
    if not path.exists():
        return 0

    import json
    with path.open("r") as f:
        runbooks = json.load(f)

    count = 0
    for runbook in runbooks:
        source_document = f"{runbook['id']}.md"
        tags = runbook.get("tags", [])
        category = runbook.get("category")
        chunks = runbook.get("chunks", [])
        for idx, chunk in enumerate(chunks):
            db.add(
                RunbookChunk(
                    source_document=source_document,
                    chunk_index=idx,
                    title=runbook.get("title"),
                    content=chunk.get("content", ""),
                    doc_metadata={
                        "tags": tags,
                        "category": category,
                        "source_title": runbook.get("title"),
                    },
                )
            )
            count += 1

    return count


def create_seed_data():
    """Create sample data for testing"""
    from datetime import datetime, timezone, timedelta
    from app.database import get_db_context

    logger.info("Creating seed data...")

    with get_db_context() as db:
        # Create sample incident (open)
        incident = Incident(
            title="Database connection pool exhausted",
            summary="Multiple alerts indicating database connection issues across production services",
            severity=SeverityLevel.CRITICAL,
            status=IncidentStatus.OPEN,
            assigned_team="platform",
            affected_services=["api-server", "worker-service", "webhook-ingress"]
        )
        db.add(incident)
        db.flush()  # Get incident ID

        # Create a resolved incident for MTTR metrics
        resolved_incident = Incident(
            title="API latency spike resolved",
            summary="Latency normalized after scaling API pods",
            severity=SeverityLevel.WARNING,
            status=IncidentStatus.RESOLVED,
            assigned_team="platform",
            affected_services=["api-gateway"],
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
            resolved_at=datetime.now(timezone.utc) - timedelta(hours=1, minutes=30),
            time_to_acknowledge=300,
            time_to_resolve=1800,
        )
        db.add(resolved_incident)

        # Create sample alerts
        base_time = datetime.now(timezone.utc) - timedelta(minutes=30)

        for i in range(3):
            alert = Alert(
                external_id=f"datadog-alert-{1000 + i}",
                source="datadog",
                title=f"High database connection count - api-server-{i}",
                message="Connection pool utilization > 95%",
                raw_payload={
                    "alert_id": f"dd-{1000 + i}",
                    "metric": "postgresql.connections",
                    "value": 95 + i,
                    "threshold": 90,
                    "host": f"api-server-{i}"
                },
                alert_timestamp=base_time + timedelta(minutes=i * 5),
                severity=SeverityLevel.CRITICAL,
                predicted_team="platform",
                confidence_score=0.92,
                service_name="api-server",
                environment="production",
                region="us-east-1",
                incident_id=incident.id
            )
            db.add(alert)

        # Create incident action
        action = IncidentAction(
            incident_id=incident.id,
            action_type=ActionType.STATUS_CHANGE,
            description="Incident created automatically from alert grouping",
            user="system",
            extra_metadata={"trigger": "auto_grouping", "alert_count": 3}
        )
        db.add(action)

        # Load sample runbooks if available
        runbooks_path = Path(__file__).resolve().parents[1] / "datasets" / "sample_runbooks.json"
        runbook_chunks_loaded = load_runbooks_from_file(db, runbooks_path)
        if runbook_chunks_loaded == 0:
            # Fallback runbook chunk
            chunk = RunbookChunk(
                source_document="database-troubleshooting.md",
                chunk_index=0,
                title="Database Connection Pool Troubleshooting",
                content="""
## Symptom: Connection Pool Exhausted

When you see "connection pool exhausted" errors:

1. Check current connections: `SELECT count(*) FROM pg_stat_activity;`
2. Identify long-running queries: `SELECT pid, now() - query_start as duration, query
   FROM pg_stat_activity WHERE state = 'active' ORDER BY duration DESC;`
3. Kill problematic queries if needed: `SELECT pg_terminate_backend(pid);`
4. Temporarily increase pool size in application config
5. Check for connection leaks in application code

**Root Causes:**
- Application not closing connections properly
- Queries taking longer than expected
- Sudden traffic spike
- Too many idle connections
                """.strip(),
                doc_metadata={
                    "tags": ["database", "troubleshooting", "connections"],
                    "category": "infrastructure",
                    "priority": "high"
                }
            )
            db.add(chunk)
            runbook_chunks_loaded = 1

        # Create sample connectors (only webhooks implemented are connected)
        connectors = [
            Connector(id="notion", name="Notion", status=ConnectorStatus.NOT_CONNECTED, detail="Runbook sync"),
            Connector(id="slack", name="Slack", status=ConnectorStatus.NOT_CONNECTED, detail="Incident channel history"),
            Connector(id="linear", name="Linear", status=ConnectorStatus.NOT_CONNECTED, detail="Issue context"),
            Connector(id="datadog", name="Datadog", status=ConnectorStatus.CONNECTED, detail="Metrics and alerts"),
            Connector(id="sentry", name="Sentry", status=ConnectorStatus.CONNECTED, detail="Error tracking"),
            Connector(id="pagerduty", name="PagerDuty", status=ConnectorStatus.NOT_CONNECTED, detail="On-call scheduling"),
        ]
        db.add_all(connectors)

        db.commit()
        logger.info("✓ Seed data created successfully")
        logger.info(f"  - Created incident #{incident.id}")
        logger.info(f"  - Created 3 alerts")
        logger.info(f"  - Created 1 incident action")
        logger.info(f"  - Created {runbook_chunks_loaded} runbook chunks")


def main():
    parser = argparse.ArgumentParser(description="Initialize OpsRelay database")
    parser.add_argument("--drop", action="store_true",
                       help="Drop existing tables before creating (WARNING: deletes all data)")
    parser.add_argument("--yes", action="store_true",
                       help="Confirm dropping tables without prompting")
    parser.add_argument("--seed", action="store_true",
                       help="Load seed data for testing")
    parser.add_argument("--check-only", action="store_true",
                       help="Only check database connectivity")

    args = parser.parse_args()

    # Step 1: Check connectivity
    logger.info("="* 60)
    logger.info("OpsRelay Database Initialization")
    logger.info("=" * 60)

    if not check_connection():
        logger.error("❌ Database connection failed!")
        logger.error("Please check your DATABASE_URL environment variable")
        sys.exit(1)

    logger.info("✓ Database connection successful")

    if args.check_only:
        logger.info("Connection check complete")
        return

    # Step 2: Drop tables if requested
    if args.drop:
        logger.warning("⚠️  DROPPING ALL TABLES...")
        if args.yes:
            drop_db()
            logger.info("✓ All tables dropped")
        else:
            confirm = input("Are you sure? This will delete all data! (yes/no): ")
            if confirm.lower() == "yes":
                drop_db()
                logger.info("✓ All tables dropped")
            else:
                logger.info("Drop cancelled")
                return

    # Step 3: Enable extensions
    enable_extensions()

    # Step 4: Create schema
    logger.info("Creating database schema...")
    init_db()
    logger.info("✓ Schema created successfully")

    # Step 5: Load seed data if requested
    if args.seed:
        create_seed_data()

    logger.info("=" * 60)
    logger.info("✓ Database initialization complete!")
    logger.info("=" * 60)

    # Print summary
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT
                schemaname,
                tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
        """))

        logger.info("\nCreated tables:")
        for row in result:
            logger.info(f"  - {row[1]} ({row[2]})")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)
