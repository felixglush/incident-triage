from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
    Float, Enum, Index, UniqueConstraint, CheckConstraint,
    event
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, timezone
import enum

# Try to import pgvector, fallback to JSON if not available
try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False

Base = declarative_base()


class SeverityLevel(str, enum.Enum):
    """Alert/Incident severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class IncidentStatus(str, enum.Enum):
    """Incident lifecycle statuses"""
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class ActionType(str, enum.Enum):
    """Types of incident actions for audit trail"""
    STATUS_CHANGE = "status_change"
    COMMENT = "comment"
    ALERT_ADDED = "alert_added"
    ALERT_REMOVED = "alert_removed"
    ASSIGNMENT = "assignment"
    ESCALATION = "escalation"


def utcnow():
    """Return timezone-aware UTC datetime"""
    return datetime.now(timezone.utc)


class Alert(Base):
    """
    Alert model stores individual monitoring alerts from various sources.

    Relationships:
    - Belongs to one Incident (many-to-one, nullable)
    - Multiple Alerts can be grouped into a single Incident
    - Alerts can exist without an Incident during the grouping process
    - If parent Incident is deleted, Alert.incident_id is set to NULL (soft link)

    Design decisions:
    - external_id is unique to prevent duplicate alert processing
    - raw_payload stored as JSONB for efficient querying
    - ML fields are nullable (populated asynchronously)
    - Indexed on source + created_at for common queries
    - incident_id is nullable to allow flexible grouping logic

    Typical lifecycle:
    1. Alert received via webhook and stored (incident_id = NULL)
    2. Celery worker processes alert (runs ML classification, entity extraction)
    3. Grouping logic matches alert to existing Incident or creates new one
    4. Alert.incident_id is updated to group with related alerts
    """
    __tablename__ = "alerts"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Source identification - MUST be unique to prevent duplicates
    external_id = Column(String(255), nullable=False, index=True)
    source = Column(String(50), nullable=False, index=True)  # datadog, sentry, pagerduty

    # Alert content
    title = Column(String(500), nullable=False)
    message = Column(Text)
    raw_payload = Column(JSONB, nullable=False)  # Use JSONB for better query performance

    # Timestamps - separate creation from actual alert time
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    alert_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)

    # ML classification results (populated asynchronously)
    severity = Column(Enum(SeverityLevel), index=True)
    predicted_team = Column(String(100), index=True)
    confidence_score = Column(Float)
    classification_source = Column(String(50), index=True)

    # Extracted entities from NER
    service_name = Column(String(200), index=True)
    environment = Column(String(50), index=True)
    region = Column(String(50))
    error_code = Column(String(100))
    entity_source = Column(String(50), index=True)
    entity_sources = Column(JSONB, nullable=True)

    # Soft delete flag
    deleted_at = Column(DateTime(timezone=True))

    # Foreign key to incident (nullable - alerts can exist before grouping)
    incident_id = Column(
        Integer,
        ForeignKey("incidents.id", ondelete="SET NULL"),
        index=True
    )

    # Relationships
    incident = relationship(
        "Incident",
        back_populates="alerts",
        lazy="select"  # Explicit lazy loading
    )

    # Table-level constraints and indexes
    __table_args__ = (
        # Unique constraint on source + external_id
        UniqueConstraint("source", "external_id", name="uq_alert_source_external_id"),

        # Composite indexes for common query patterns
        Index("ix_alerts_source_created", "source", "created_at"),
        Index("ix_alerts_severity_created", "severity", "created_at"),
        Index("ix_alerts_service_created", "service_name", "created_at"),
        Index("ix_alerts_incident_created", "incident_id", "created_at"),

        # GIN index on JSONB column for efficient JSON queries
        Index("ix_alerts_raw_payload_gin", "raw_payload", postgresql_using="gin"),

        # Check constraint for confidence score
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_alert_confidence_range"
        ),
    )

    def __repr__(self):
        return f"<Alert(id={self.id}, source={self.source}, external_id={self.external_id})>"


class Incident(Base):
    """
    Incident model groups related alerts and tracks resolution lifecycle.

    Relationships:
    - Has many Alerts (one-to-many, nullable FK - soft link)
      * Alert.incident_id can be NULL before grouping or if Incident is deleted
      * Accessed via: incident.alerts (lazy="select")
      * FK constraint: ondelete="SET NULL" - Alerts are preserved if Incident deleted
    - Has many IncidentActions (one-to-many, non-nullable FK - hard link)
      * IncidentAction.incident_id must always reference an Incident
      * Accessed via: incident.actions (lazy="select", sorted by timestamp DESC)
      * FK constraint: ondelete="CASCADE" - Actions deleted if Incident deleted (audit trail)

    Design decisions:
    - updated_at auto-updates on any change (via SQLAlchemy event listener)
    - affected_services stored as JSONB array for flexible service tracking
    - Indexed on status + created_at for dashboard queries (hot path)
    - SLA metrics (time_to_acknowledge, time_to_resolve) calculated on resolution

    Typical lifecycle:
    1. Incident created when first alert is grouped (or manually created)
    2. Multiple Alerts are grouped into this Incident via Alert.incident_id updates
    3. IncidentActions are logged for every status change, comment, or assignment
    4. Incident moves through statuses: OPEN → INVESTIGATING → RESOLVED → CLOSED
    5. Once RESOLVED, time_to_resolve is calculated for SLA tracking
    """
    __tablename__ = "incidents"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Status and assignment
    status = Column(
        Enum(IncidentStatus),
        default=IncidentStatus.OPEN,
        nullable=False,
        index=True
    )
    assigned_team = Column(String(100), index=True)
    assigned_user = Column(String(200))

    # Core fields
    title = Column(String(500), nullable=False)
    summary = Column(Text)  # ML-generated summary
    severity = Column(Enum(SeverityLevel), nullable=False, index=True)
    summary_citations = Column(JSONB)  # [{type, id, title, score, source_document}]
    next_steps = Column(JSONB)  # ["step one", "step two"]

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    resolved_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))

    # Metadata
    affected_services = Column(JSONB, default=list)  # Array of service names
    root_cause = Column(Text)
    resolution_notes = Column(Text)

    # Embedding for similarity search
    if HAS_PGVECTOR:
        incident_embedding = Column(Vector(384))
    else:
        incident_embedding = Column(JSONB)

    # Metrics for SLA tracking
    time_to_acknowledge = Column(Integer)  # Seconds
    time_to_resolve = Column(Integer)  # Seconds

    # Soft delete
    deleted_at = Column(DateTime(timezone=True))

    # Relationships
    alerts = relationship(
        "Alert",
        back_populates="incident",
        lazy="select",
        cascade="all, delete-orphan"  # When incident deleted, alerts are unlinked (SET NULL)
    )
    actions = relationship(
        "IncidentAction",
        back_populates="incident",
        lazy="select",
        cascade="all, delete-orphan",
        order_by="IncidentAction.timestamp.desc()"
    )

    # Table-level constraints and indexes
    __table_args__ = (
        # Composite indexes for dashboard and reporting queries
        Index("ix_incidents_status_created", "status", "created_at"),
        Index("ix_incidents_status_severity", "status", "severity"),
        Index("ix_incidents_team_status", "assigned_team", "status"),
        Index("ix_incidents_severity_created", "severity", "created_at"),

        # GIN index for JSONB array queries on affected_services
        Index("ix_incidents_affected_services_gin", "affected_services", postgresql_using="gin"),

        Index("ix_incidents_embedding_vector", "incident_embedding",
              postgresql_using="ivfflat",
              postgresql_with={"lists": 100}) if HAS_PGVECTOR else None,

        # Check constraints
        CheckConstraint(
            "time_to_acknowledge IS NULL OR time_to_acknowledge >= 0",
            name="ck_incident_tta_positive"
        ),
        CheckConstraint(
            "time_to_resolve IS NULL OR time_to_resolve >= 0",
            name="ck_incident_ttr_positive"
        ),
    )

    def __repr__(self):
        return f"<Incident(id={self.id}, status={self.status}, severity={self.severity})>"


class IncidentAction(Base):
    """
    Audit trail of actions taken during incident response.

    Relationships:
    - Belongs to exactly one Incident (many-to-one, non-nullable FK)
    - Must be associated with an Incident at creation (incident_id required)
    - Accessed via: incident.actions
    - If Incident is deleted, all its IncidentActions are also deleted (CASCADE)
    - Represents immutable history - actions should never be updated or deleted

    Design decisions:
    - Immutable audit log (no updates/deletes in production)
    - Indexed on incident_id + timestamp for timeline queries (audit trail access)
    - Non-nullable FK enforces referential integrity - each action tied to an incident
    - CASCADE delete matches the lifecycle - incident deletion removes entire history
    - extra_metadata (JSONB) stores contextual data (e.g., previous status, new status)

    Typical actions logged:
    - STATUS_CHANGE: OPEN → INVESTIGATING → RESOLVED
    - COMMENT: User added a comment during investigation
    - ALERT_ADDED: New alert was grouped with this incident
    - ALERT_REMOVED: Alert was manually ungrouped
    - ASSIGNMENT: Incident assigned to user/team
    - ESCALATION: Escalation triggered
    """
    __tablename__ = "incident_actions"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Foreign key (required)
    incident_id = Column(
        Integer,
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Action details
    action_type = Column(Enum(ActionType), nullable=False, index=True)
    description = Column(Text, nullable=False)
    user = Column(String(200))  # Username or system identifier
    extra_metadata = Column(JSONB)  # Additional structured data

    # Timestamp
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    # Relationship
    incident = relationship("Incident", back_populates="actions")

    # Table-level constraints and indexes
    __table_args__ = (
        # Composite index for timeline queries
        Index("ix_actions_incident_timestamp", "incident_id", "timestamp"),
        Index("ix_actions_type_timestamp", "action_type", "timestamp"),
    )

    def __repr__(self):
        return f"<IncidentAction(id={self.id}, type={self.action_type}, incident_id={self.incident_id})>"


class RunbookChunk(Base):
    """
    Stores documentation chunks for RAG (Retrieval Augmented Generation).

    Relationships:
    - NO relationships (independent table)
    - Not directly linked to Incident or Alert entities
    - Enables reusable knowledge base that evolves independently
    - Queried by semantic similarity, not by incident ID

    Design decisions:
    - Embedding dimension: 384 (all-MiniLM-L6-v2) or 768 (BERT)
    - Uses pgvector (Vector(384)) if available, otherwise JSONB for compatibility
    - source_document stores filename for citation (no FK to other table)
    - chunk_index allows proper ordering of chunks within a document
    - Unique constraint on (source_document, chunk_index) prevents duplicate chunks
    - Full-text search index (GIN with trigram ops) for keyword matching
    - Vector similarity index (IVFFLAT, 100 lists) for semantic search

    Typical usage:
    1. Documentation parsed and split into chunks (init_db.py example)
    2. Chunks embedded with sentence-transformer model
    3. User query embedded with same model
    4. Vector similarity search returns top-k relevant chunks (pgvector IVFFLAT)
    5. Chunks sent to Claude API along with query for answer synthesis
    6. Response includes source citations from source_document field

    Example queries:
    - SELECT * FROM runbook_chunks WHERE embedding <-> query_embedding LIMIT 5;
    - SELECT * FROM runbook_chunks WHERE content @@ to_tsquery('database|connection');
    """
    __tablename__ = "runbook_chunks"

    # Primary key
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Document source tracking
    source_document = Column(String(500), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)

    # Content
    title = Column(String(500))
    content = Column(Text, nullable=False)

    # Vector embedding for similarity search
    # Using 384 dimensions for all-MiniLM-L6-v2 model
    if HAS_PGVECTOR:
        embedding = Column(Vector(384))
    else:
        embedding = Column(JSONB)  # Fallback to JSONB

    # Metadata for filtering (renamed to avoid SQLAlchemy reserved word)
    doc_metadata = Column(JSONB)  # tags, category, last_updated, etc.

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    # Soft delete
    deleted_at = Column(DateTime(timezone=True))

    # Table-level constraints and indexes
    __table_args__ = (
        # Unique constraint to prevent duplicate chunks
        UniqueConstraint("source_document", "chunk_index", name="uq_runbook_doc_chunk"),

        # Index for ordering chunks within a document
        Index("ix_runbook_source_index", "source_document", "chunk_index"),

        # Full-text search index on content
        Index("ix_runbook_content_fts", "content", postgresql_using="gin",
              postgresql_ops={"content": "gin_trgm_ops"}),

        # Vector similarity index (only if pgvector available)
        Index("ix_runbook_embedding_vector", "embedding",
              postgresql_using="ivfflat",
              postgresql_with={"lists": 100}) if HAS_PGVECTOR else None,
    )

    def __repr__(self):
        return f"<RunbookChunk(id={self.id}, document={self.source_document}, chunk={self.chunk_index})>"


# SQLAlchemy event listeners for automatic timestamp updates
@event.listens_for(Alert, "before_update")
@event.listens_for(Incident, "before_update")
@event.listens_for(RunbookChunk, "before_update")
def receive_before_update(_mapper, _connection, target):
    """Automatically update updated_at timestamp on any model change"""
    target.updated_at = utcnow()
