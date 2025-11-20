Database models for OpsRelay incident management system.

This module defines the SQLAlchemy ORM models with production-ready best practices:
- Proper indexes on foreign keys and frequently queried columns
- Composite indexes for common query patterns
- pgvector support for embeddings
- Proper cascading delete behaviors
- UTC timezone handling
- Relationship lazy loading configuration

## Entity Relationship Model

### Core Tables and Relationships:

1. **alerts** → **incidents** (Many-to-One, soft relationship)
   - An Alert can belong to one Incident or none (nullable FK)
   - An Incident has many Alerts
   - When an Incident is deleted, associated Alerts have their incident_id set to NULL
   - Use case: Multiple monitoring alerts from different sources are grouped into a single Incident

2. **incidents** ← **incident_actions** (One-to-Many, strict cascade)
   - An Incident has many IncidentActions
   - An IncidentAction must belong to exactly one Incident (non-nullable FK)
   - When an Incident is deleted, all its IncidentActions are also deleted (CASCADE)
   - Use case: Immutable audit trail of all status changes, comments, and assignments during incident lifecycle

3. **runbook_chunks** (No foreign keys, independent table)
   - Standalone documentation chunks used for RAG (Retrieval Augmented Generation)
   - Embedded with vector representations for semantic search
   - References source_document for citation tracking but no FK constraint
   - Use case: Knowledge base for copilot assistance; queried by semantic similarity, not linked to specific incidents

### Relationship Diagram:

```
    alerts (many)
        ↓ [incident_id FK, ondelete=SET NULL]
    incidents (one)
        ↑ [back_populates="alerts", cascade="all, delete-orphan"]

    incident_actions (many)
        ↑ [incident_id FK, ondelete=CASCADE]
    incidents (one)
        ↓ [back_populates="actions", cascade="all, delete-orphan"]

    runbook_chunks (independent)
        ✗ [no relationships, used for RAG queries]
```

### Key Design Patterns:

- **Soft Links (Alerts)**: Alert doesn't require an Incident - can exist independently before grouping
  occurs, allowing for flexible grouping logic.

- **Hard Links (Actions)**: IncidentAction must belong to an Incident - represents immutable audit
  trail that should be deleted if incident is removed.

- **Knowledge Base (RunbookChunks)**: Independent of incident data - enables reusable RAG system
  that improves over time as documentation evolves.

- **Cascading Deletes**: Define behavior at relationship level (cascade=), not FK level, for
  cleaner semantics and easier migration to soft deletes.