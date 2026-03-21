"""
Tests for upsert_markdown_document() with structured chunker.
Uses db_session fixture (transactional rollback, no real commits needed).
"""
import pytest
from sqlalchemy import func

from app.models import RunbookChunk, SourceDocument
from app.services.ingestion import upsert_markdown_document


STRUCTURED_DOC = """# Queue Workers Runbook

## Service Overview

Queue workers process background jobs.

### INC-2024-0099 — Worker Memory Leak

**Severity:** P1

Workers ran out of memory after 6 hours.

**Root Cause:**
A message handler held references after ack.

**Resolution:**
Restart workers and deploy fix.
"""

FLAT_DOC = """# Simple Guide

This is a flat document with no section headers.

It has multiple paragraphs but no H2 or H3 headings.
"""


@pytest.mark.unit
def test_upsert_writes_section_header_and_content(db_session):
    count = upsert_markdown_document(
        db_session,
        source_document="queue-workers-runbook.md",
        source="runbooks",
        source_uri="file://queue-workers-runbook.md",
        content=STRUCTURED_DOC,
    )
    db_session.flush()
    assert count > 0

    chunks = (
        db_session.query(RunbookChunk)
        .filter_by(source_document="queue-workers-runbook.md", source="runbooks")
        .all()
    )
    assert chunks

    # All chunks for the incident section carry section_header
    incident_chunks = [c for c in chunks if c.section_header == "INC-2024-0099 — Worker Memory Leak"]
    assert incident_chunks, "Expected chunks for the INC-2024-0099 section"

    # section_content on incident chunks contains the full section
    sc = incident_chunks[0].section_content
    assert "Worker Memory Leak" in sc
    assert "Restart workers" in sc


@pytest.mark.unit
def test_upsert_section_header_in_search_tsv(db_session):
    """section_header text (including incident IDs) should be searchable via BM25."""
    upsert_markdown_document(
        db_session,
        source_document="queue-workers-runbook.md",
        source="runbooks",
        source_uri=None,
        content=STRUCTURED_DOC,
    )
    db_session.flush()

    # search_tsv is not null on chunks that have a section_header
    chunks_with_tsv = (
        db_session.query(RunbookChunk)
        .filter(
            RunbookChunk.source_document == "queue-workers-runbook.md",
            RunbookChunk.search_tsv.isnot(None),
        )
        .all()
    )
    assert chunks_with_tsv


@pytest.mark.unit
def test_upsert_flat_doc_section_content_is_full_document(db_session):
    """Flat docs (no ## / ### headers): section_content equals the full document text."""
    upsert_markdown_document(
        db_session,
        source_document="simple-guide.md",
        source="runbooks",
        source_uri=None,
        content=FLAT_DOC,
    )
    db_session.flush()

    chunks = (
        db_session.query(RunbookChunk)
        .filter_by(source_document="simple-guide.md", source="runbooks")
        .all()
    )
    assert chunks
    for chunk in chunks:
        assert chunk.section_content == FLAT_DOC.strip()
        assert chunk.section_header == "Simple Guide"


@pytest.mark.unit
def test_upsert_unchanged_document_skips(db_session):
    """Re-ingesting an identical document returns 0 (no-op)."""
    upsert_markdown_document(
        db_session,
        source_document="queue-workers-runbook.md",
        source="runbooks",
        source_uri=None,
        content=STRUCTURED_DOC,
    )
    db_session.flush()

    count2 = upsert_markdown_document(
        db_session,
        source_document="queue-workers-runbook.md",
        source="runbooks",
        source_uri=None,
        content=STRUCTURED_DOC,
    )
    assert count2 == 0


@pytest.mark.unit
def test_upsert_changed_document_replaces_chunks(db_session):
    """Re-ingesting a changed document replaces all chunks."""
    upsert_markdown_document(
        db_session,
        source_document="queue-workers-runbook.md",
        source="runbooks",
        source_uri=None,
        content=STRUCTURED_DOC,
    )
    db_session.flush()

    modified = STRUCTURED_DOC + "\n\n### INC-2024-0100 — New Incident\n\nNew content here.\n"
    count2 = upsert_markdown_document(
        db_session,
        source_document="queue-workers-runbook.md",
        source="runbooks",
        source_uri=None,
        content=modified,
    )
    db_session.flush()
    assert count2 > 0

    new_chunks = (
        db_session.query(RunbookChunk)
        .filter(
            RunbookChunk.source_document == "queue-workers-runbook.md",
            RunbookChunk.section_header == "INC-2024-0100 — New Incident",
        )
        .all()
    )
    assert new_chunks
