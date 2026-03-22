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

### INC-2024-0099 — Xyzzy Worker Memory Leak

**Severity:** P1

Workers ran out of memory after 6 hours.

**Root Cause:**
A message handler held references after ack.

**Resolution:**
Restart workers and deploy fix.
"""

FLAT_DOC = """# Simple Guide

This is a flat document with no section headers. It contains enough content to
fill the first paragraph so that the chunker can split it into multiple pieces.
Each paragraph here is intentionally verbose so that the total character count
pushes beyond the default max_chars threshold and forces at least two chunks.

The second paragraph continues the guide with more detail about the subject at
hand. It also has no H2 or H3 headings anywhere in the document. The purpose of
having this much text is to ensure the structured chunker splits this flat
document into multiple sub-chunks, each with its own bounded section_content.

A third paragraph appears here to provide further assurance that the document
is long enough. Without multiple paragraphs of reasonable length the chunker
would produce a single chunk whose content equals the full document, making it
impossible to distinguish the new behaviour from the old buggy behaviour in
automated tests. This paragraph pushes the total well past 1000 characters.
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
    incident_chunks = [c for c in chunks if c.section_header == "INC-2024-0099 — Xyzzy Worker Memory Leak"]
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

    # Check that a word ONLY in the section_header (not in any body text) is searchable
    # "Xyzzy" appears exclusively in the section header, so a match proves section_header
    # text is included when building search_tsv.
    matching = (
        db_session.query(RunbookChunk)
        .filter(
            RunbookChunk.search_tsv.op("@@")(func.to_tsquery("english", "xyzzy"))
        )
        .all()
    )
    assert len(matching) > 0, "Expected section_header tokens to be searchable in search_tsv"


@pytest.mark.unit
def test_upsert_flat_doc_chunks_have_bounded_section_content(db_session):
    """
    Flat docs (no ## / ### headers): each chunk's section_content equals its
    own content — NOT the full document. This prevents unbounded parent-doc
    text from being injected into LLM prompts.
    """
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
        # section_content must equal content, not the full document
        assert chunk.section_content == chunk.content
        assert chunk.section_header == "Simple Guide"
        # no chunk's section_content should be the full doc
        assert chunk.section_content != FLAT_DOC.strip()


@pytest.mark.unit
def test_flat_doc_large_emits_warning(caplog):
    """Flat docs over 6000 chars should log a warning and still produce chunks."""
    import logging
    large_flat = "Word " * 1500  # ~7500 chars, no headers
    from app.services.ingestion import chunk_markdown_structured
    with caplog.at_level(logging.WARNING, logger="app.services.ingestion"):
        chunks = chunk_markdown_structured(large_flat)
    assert chunks  # produced at least one chunk
    assert any("no ## headers" in r.message for r in caplog.records)


@pytest.mark.unit
def test_flat_doc_no_title_chunks_have_section_header_none_or_empty():
    """Flat doc with no # title: section_header should be None (not crash)."""
    from app.services.ingestion import chunk_markdown_structured
    no_title_doc = "Just some content with no heading at all.\n\nAnother paragraph here."
    chunks = chunk_markdown_structured(no_title_doc)
    assert chunks
    for chunk in chunks:
        # section_content must equal content (same flat-doc rule)
        assert chunk.section_content == chunk.content
        # extract_title returns None when there is no # heading; section_header mirrors title
        assert chunk.section_header is None
        assert chunk.title is None


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

    chunk_count_before = (
        db_session.query(RunbookChunk)
        .filter_by(source_document="queue-workers-runbook.md", source="runbooks")
        .count()
    )

    count2 = upsert_markdown_document(
        db_session,
        source_document="queue-workers-runbook.md",
        source="runbooks",
        source_uri=None,
        content=STRUCTURED_DOC,
    )
    db_session.flush()
    assert count2 == 0

    chunk_count_after = (
        db_session.query(RunbookChunk)
        .filter_by(source_document="queue-workers-runbook.md", source="runbooks")
        .count()
    )
    assert chunk_count_after == chunk_count_before, (
        f"Chunk count changed after no-op upsert: {chunk_count_before} -> {chunk_count_after}"
    )


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

    # Replace the original section with a completely different one so the old
    # section_header ("INC-2024-0099 — Xyzzy Worker Memory Leak") is absent from
    # the new document and must not survive re-ingestion.
    modified = """# Queue Workers Runbook

## Service Overview

Queue workers process background jobs.

### INC-2024-0100 — New Incident

**Severity:** P2

New content here describing the new incident.

**Resolution:**
Apply the fix and monitor.
"""
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

    # Verify no chunks from the OLD document version remain — the old section
    # header only existed in the first version and must be gone after re-ingestion.
    old_chunks = (
        db_session.query(RunbookChunk)
        .filter(
            RunbookChunk.source_document == "queue-workers-runbook.md",
            RunbookChunk.section_header == "INC-2024-0099 — Xyzzy Worker Memory Leak",
        )
        .all()
    )
    assert not old_chunks, (
        f"Expected old chunks to be replaced, but {len(old_chunks)} chunk(s) with "
        "the old section header still exist"
    )
