# Parent-Document Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the paragraph-based chunker with a header-aware structured chunker that indexes small sub-chunks for precise vector matching and stores the full H3 section as `section_content` for complete LLM context.

**Architecture:** `chunk_markdown_structured()` splits markdown on `##`/`###` header boundaries (Pass 1), then sub-splits each section by paragraph into ≤1,000-char child chunks (Pass 2). Each child carries `section_content` (the full parent section) and `section_header`. Retrieval deduplicates results by `(source_document, section_header)` and returns a `context` key pointing to `section_content`.

**Tech Stack:** Python, SQLAlchemy, PostgreSQL/pgvector, pytest. No new dependencies.

---

## File Map

| File | Change |
|---|---|
| `backend/app/models/database.py` | Add `section_header`, `section_content` columns to `RunbookChunk` |
| `backend/app/services/ingestion.py` | Add fields to `DocumentChunk`; add `_extract_sections()`, `_split_section()`, `chunk_markdown_structured()`; update `upsert_markdown_document()` |
| `backend/app/services/incident_similarity.py` | Inflate limit, deduplicate by section, add `context` key, update `_rerank_boost` call in Jaccard path |
| `tests/backend/unit/test_chunking.py` | Extend with structured chunker tests (no DB needed) |
| `tests/backend/unit/test_ingestion.py` | New file — DB-backed ingestion tests |
| `tests/backend/unit/test_incident_similarity.py` | New file — retrieval dedup + context key tests |

---

## Task 1: Add schema columns to `RunbookChunk`

**Files:**
- Modify: `backend/app/models/database.py:388–400`

This must be done first so every subsequent import of `RunbookChunk` sees the new columns.

- [ ] **Step 1: Add `section_header` and `section_content` columns**

Open `backend/app/models/database.py`. After the `title` column (line 388), add:

```python
# Parent section for small-to-big retrieval
section_header = Column(String(500))          # H2/H3 header text, e.g. "INC-2024-0156 — Redis OOM"
section_content = Column(Text)                # Full parent section text shared across child chunks
```

Both are nullable (no `nullable=False`) so existing rows without these columns still load.

- [ ] **Step 2: Verify the model loads cleanly**

```bash
cd /Users/felix/incident-triage
python -c "from app.models.database import RunbookChunk; print(RunbookChunk.section_header, RunbookChunk.section_content)"
```

Expected output: two Column objects printed, no ImportError.

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/database.py
git commit -m "feat(schema): add section_header and section_content to RunbookChunk"
```

---

## Task 2: Implement structured chunker (TDD)

**Files:**
- Modify: `tests/backend/unit/test_chunking.py`
- Modify: `backend/app/services/ingestion.py`

### 2a — Write the failing tests

- [ ] **Step 1: Add structured chunker tests to `test_chunking.py`**

Append to the bottom of `tests/backend/unit/test_chunking.py`:

```python
from app.services.ingestion import chunk_markdown_structured


# --- chunk_markdown_structured tests ---

RUNBOOK_DOC = """# Auth & Sessions Runbook

## Service Overview

The auth service manages login and sessions.

It uses Redis for session storage.

## Recorded Incidents

### INC-2024-0001 — Redis OOM

**Severity:** P0 | **Date:** 2024-07-04

All new logins failed with OOM error.

**Root Cause:**
TTL was extended without capacity planning.

**Resolution Steps:**

1. Switch eviction policy to allkeys-lru.
2. Increase maxmemory to 16gb.
3. Revert TTL to 7 days.

### INC-2024-0002 — JWT Key Rotation Failure

**Severity:** P1

JWT signing failed after key rotation.

**Root Cause:**
Dual-key window was not configured.
"""


def test_structured_h3_section_header():
    """Each chunk carries the header of its containing H3 section."""
    chunks = chunk_markdown_structured(RUNBOOK_DOC)
    inc1_chunks = [c for c in chunks if c.section_header == "INC-2024-0001 — Redis OOM"]
    assert len(inc1_chunks) >= 1
    inc2_chunks = [c for c in chunks if c.section_header == "INC-2024-0002 — JWT Key Rotation Failure"]
    assert len(inc2_chunks) >= 1


def test_structured_siblings_share_section_content():
    """All child chunks within one H3 section share the identical section_content."""
    chunks = chunk_markdown_structured(RUNBOOK_DOC, max_chars=200)
    inc1_chunks = [c for c in chunks if c.section_header == "INC-2024-0001 — Redis OOM"]
    # With small max_chars this section should produce multiple sub-chunks
    assert len(inc1_chunks) >= 2
    # All siblings share the same section_content
    contents = {c.section_content for c in inc1_chunks}
    assert len(contents) == 1
    # section_content contains the full section text
    sc = inc1_chunks[0].section_content
    assert "Redis OOM" in sc
    assert "Switch eviction policy" in sc
    assert "Revert TTL" in sc


def test_structured_overlap_does_not_cross_section_boundary():
    """Overlap text from the last chunk of section A must not appear in the first chunk of section B."""
    chunks = chunk_markdown_structured(RUNBOOK_DOC, max_chars=200, overlap=50)
    # Find the first chunk of INC-2024-0002
    inc2_chunks = [c for c in chunks if c.section_header == "INC-2024-0002 — JWT Key Rotation Failure"]
    assert inc2_chunks, "Expected chunks for INC-2024-0002"
    first_inc2 = inc2_chunks[0]
    # Its content must NOT start with text from INC-0001
    assert "Redis OOM" not in first_inc2.content
    assert "allkeys-lru" not in first_inc2.content


def test_structured_flat_doc_fallback():
    """A doc with no ## or ### headers is treated as one section."""
    flat = "# My Doc\n\nFirst paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    chunks = chunk_markdown_structured(flat)
    assert all(c.section_header == "My Doc" for c in chunks)
    assert all(c.section_content == flat.strip() for c in chunks)


def test_structured_h2_only_splits_on_h2():
    """A doc with only H2 headers (no H3) uses H2 as section boundaries."""
    doc = "# Title\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B."
    chunks = chunk_markdown_structured(doc)
    headers = {c.section_header for c in chunks}
    assert "Section A" in headers
    assert "Section B" in headers


def test_structured_oversized_paragraph_stays_intact():
    """A single paragraph exceeding max_chars becomes its own chunk; section_content is preserved."""
    long_para = "x " * 600  # ~1200 chars
    doc = f"# Title\n\n### Big Section\n\n{long_para}\n\nShort para."
    chunks = chunk_markdown_structured(doc, max_chars=300)
    big_section = [c for c in chunks if c.section_header == "Big Section"]
    assert len(big_section) >= 1
    # section_content contains both paragraphs regardless of chunk split
    assert long_para.strip() in big_section[0].section_content


def test_structured_chunk_index_is_global_sequential():
    """chunk_index increments across all sections, not per-section."""
    chunks = chunk_markdown_structured(RUNBOOK_DOC)
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_structured_title_propagated_to_all_chunks():
    """title field contains the document H1 on every chunk."""
    chunks = chunk_markdown_structured(RUNBOOK_DOC)
    assert all(c.title == "Auth & Sessions Runbook" for c in chunks)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/felix/incident-triage
pytest tests/backend/unit/test_chunking.py -k "structured" -v 2>&1 | tail -20
```

Expected: all 8 new tests fail with `ImportError: cannot import name 'chunk_markdown_structured'`.

### 2b — Implement the chunker

- [ ] **Step 3: Add helper functions and `chunk_markdown_structured()` to `ingestion.py`**

Open `backend/app/services/ingestion.py`. First, update the `DocumentChunk` dataclass (currently lines 15–19):

```python
@dataclass
class DocumentChunk:
    content: str
    chunk_index: int
    title: Optional[str] = None
    section_header: Optional[str] = None  # H2/H3 header text for this section
    section_content: Optional[str] = None  # Full parent section text
```

Then add three new functions after `extract_title()` (after line 31):

```python
def _extract_sections(text: str, title: Optional[str]) -> List[tuple]:
    """
    Split markdown text into (section_header, section_content) pairs on ## / ### boundaries.
    Content before the first ## or ### header becomes a preamble attributed to the document title.
    Returns list of (header: str | None, content: str) tuples, skipping empty sections.
    """
    lines = text.splitlines()
    sections: List[tuple] = []
    current_header: Optional[str] = title
    current_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        is_boundary = stripped.startswith("## ") or stripped.startswith("### ")
        if is_boundary:
            content = "\n".join(current_lines).strip()
            if content:
                sections.append((current_header, content))
            current_header = stripped.lstrip("#").strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    content = "\n".join(current_lines).strip()
    if content:
        sections.append((current_header, content))

    # Filter out thin sections that contain only a header line (no real content).
    # This happens when a ## section immediately precedes ### sub-sections with no
    # body text of its own — emitting a one-line chunk would pollute the index.
    return [
        (h, c) for h, c in sections
        if c and len(c.splitlines()) > 1
    ]


def _split_section(text: str, max_chars: int, overlap: int) -> List[str]:
    """
    Split section text into sub-chunks by paragraph boundaries (blank lines).
    Overlap is applied only within the section — never across section boundaries.
    A single paragraph larger than max_chars becomes its own chunk unsplit.
    Returns at least one element (the full text if no blank lines found).
    """
    lines = text.splitlines()
    paragraphs: List[str] = []
    buffer: List[str] = []

    for line in lines:
        if line.strip() == "" and buffer:
            paragraphs.append("\n".join(buffer).strip())
            buffer = []
        else:
            buffer.append(line)
    if buffer:
        paragraphs.append("\n".join(buffer).strip())

    sub_chunks: List[str] = []
    current = ""

    for para in paragraphs:
        if not para:
            continue
        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}".strip()
        else:
            if current.strip():
                sub_chunks.append(current.strip())
            current = para

    if current.strip():
        sub_chunks.append(current.strip())

    # Apply within-section overlap only
    if overlap > 0 and len(sub_chunks) > 1:
        for i in range(1, len(sub_chunks)):
            overlap_text = sub_chunks[i - 1][-overlap:]
            sub_chunks[i] = f"{overlap_text}\n{sub_chunks[i]}"

    return sub_chunks if sub_chunks else [text.strip()]


def chunk_markdown_structured(
    text: str, max_chars: int = 1000, overlap: int = 150
) -> List[DocumentChunk]:
    """
    Structure-aware chunker. Splits on ## / ### header boundaries first,
    then sub-splits each section by paragraph into <= max_chars child chunks.

    Each child chunk carries:
      - content:         small sub-chunk text for embedding/indexing
      - section_header:  H2/H3 header of the parent section (for citations)
      - section_content: full parent section text (for LLM context — the "big" in small-to-big)
      - title:           document H1 title
      - chunk_index:     global sequential index across all sections

    Flat-doc fallback: if no ## or ### headers exist, the entire document is
    treated as one section (section_content = full document).
    """
    lines = text.splitlines()
    title = extract_title(lines)

    has_headers = any(
        l.strip().startswith("## ") or l.strip().startswith("### ") for l in lines
    )

    if has_headers:
        sections = _extract_sections(text, title)
    else:
        sections = [(title, text.strip())]

    chunks: List[DocumentChunk] = []

    for section_header, section_content in sections:
        sub_chunks = _split_section(section_content, max_chars, overlap)
        for sub_content in sub_chunks:
            chunks.append(
                DocumentChunk(
                    content=sub_content,
                    chunk_index=len(chunks),
                    title=title,
                    section_header=section_header,
                    section_content=section_content,
                )
            )

        if len(section_content) > 6000:
            import logging
            logging.getLogger(__name__).warning(
                "Large section_content (%d chars) for section_header=%r — "
                "consider splitting this section",
                len(section_content),
                section_header,
            )

    return chunks
```

- [ ] **Step 4: Run tests — expect them to pass**

```bash
cd /Users/felix/incident-triage
pytest tests/backend/unit/test_chunking.py -v 2>&1 | tail -20
```

Expected: all tests pass (including the original 2 + new 8).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ingestion.py tests/backend/unit/test_chunking.py
git commit -m "feat(chunking): add chunk_markdown_structured with header-aware splitting"
```

---

## Task 3: Update ingestion pipeline (TDD)

**Files:**
- Create: `tests/backend/unit/test_ingestion.py`
- Modify: `backend/app/services/ingestion.py:91,166–179`

### 3a — Write the failing tests

- [ ] **Step 1: Create `tests/backend/unit/test_ingestion.py`**

```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/felix/incident-triage
pytest tests/backend/unit/test_ingestion.py -v 2>&1 | tail -20
```

Expected: tests fail — `section_header` and `section_content` are not yet written by `upsert_markdown_document`.

### 3b — Update `upsert_markdown_document()`

- [ ] **Step 3: Update `upsert_markdown_document()` in `ingestion.py`**

Three changes in this function:

**Change 1** — Line 91: replace `chunk_markdown` call with `chunk_markdown_structured`:
```python
# Before
chunks = chunk_markdown(content)

# After
chunks = chunk_markdown_structured(content)
```

**Change 2** — Line 166: update `search_text` to include `section_header`:
```python
# Before
search_text = f"{chunk.title or ''} {chunk.content}".strip()

# After
search_text = " ".join(filter(None, [chunk.section_header, chunk.title, chunk.content])).strip()
```

**Change 3** — Lines 167–179: add `section_header` and `section_content` to the `RunbookChunk` constructor:
```python
db.add(
    RunbookChunk(
        source_document=source_document,
        chunk_index=chunk.chunk_index,
        title=chunk.title,
        content=chunk.content,
        section_header=chunk.section_header,      # NEW
        section_content=chunk.section_content,    # NEW
        search_tsv=func.to_tsvector("english", search_text),
        embedding=embed_text(chunk.content),
        doc_metadata=metadata,
        source=source,
        source_uri=source_uri,
    )
)
```

- [ ] **Step 4: Run ingestion tests — expect pass**

```bash
cd /Users/felix/incident-triage
pytest tests/backend/unit/test_ingestion.py -v 2>&1 | tail -20
```

Expected: all 5 tests pass.

- [ ] **Step 5: Run full unit suite to check for regressions**

```bash
cd /Users/felix/incident-triage
pytest tests/backend/unit/ -v 2>&1 | tail -30
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/ingestion.py tests/backend/unit/test_ingestion.py
git commit -m "feat(ingestion): switch to chunk_markdown_structured, write section fields to DB"
```

---

## Task 4: Update retrieval — deduplication + context key (TDD)

**Files:**
- Create: `tests/backend/unit/test_incident_similarity.py`
- Modify: `backend/app/services/incident_similarity.py`

### 4a — Write the failing tests

- [ ] **Step 1: Create `tests/backend/unit/test_incident_similarity.py`**

```python
"""
Tests for find_similar_runbook_chunks() — deduplication, context key, Jaccard fallback.
Uses db_session with unit (transactional rollback) strategy.
pgvector is skipped automatically if unavailable; Jaccard fallback runs instead.
"""
import pytest

from app.models import RunbookChunk
from app.services.incident_similarity import find_similar_runbook_chunks
from app.services.embeddings import embed_text


def _make_chunk(db, *, source_document, chunk_index, content, section_header=None, section_content=None, title="Test Doc", source="runbooks"):
    chunk = RunbookChunk(
        source_document=source_document,
        chunk_index=chunk_index,
        title=title,
        content=content,
        section_header=section_header,
        section_content=section_content or content,
        embedding=embed_text(content),
        source=source,
    )
    db.add(chunk)
    return chunk


@pytest.mark.unit
def test_context_key_uses_section_content(db_session):
    """result['context'] returns section_content when present."""
    db_session.flush()
    chunk = _make_chunk(
        db_session,
        source_document="runbook.md",
        chunk_index=0,
        content="Short sub-chunk about Redis OOM.",
        section_header="INC-2024-0001 — Redis OOM",
        section_content="Full section: Redis OOM details plus resolution steps.",
    )
    db_session.flush()

    query_embedding = embed_text("Redis login failure")
    results = find_similar_runbook_chunks(db_session, query_embedding, "Redis login failure", limit=5)

    assert results, "Expected at least one result"
    result = results[0]
    assert "context" in result
    assert result["context"] == "Full section: Redis OOM details plus resolution steps."


@pytest.mark.unit
def test_context_key_falls_back_to_content_when_section_content_null(db_session):
    """result['context'] falls back to chunk.content when section_content is NULL."""
    chunk = _make_chunk(
        db_session,
        source_document="legacy.md",
        chunk_index=0,
        content="Legacy chunk content with no section.",
        section_header=None,
        section_content=None,
    )
    chunk.section_content = None  # explicitly NULL
    db_session.flush()

    query_embedding = embed_text("legacy chunk content")
    results = find_similar_runbook_chunks(db_session, query_embedding, "legacy chunk content", limit=5)

    assert results
    result = results[0]
    assert result["context"] == "Legacy chunk content with no section."


@pytest.mark.unit
def test_deduplication_collapses_siblings_to_one_result(db_session):
    """Multiple sub-chunks from same section collapse to one result (highest score wins)."""
    section_content = "Full incident: Redis OOM. Root cause: TTL too long. Fix: allkeys-lru."
    section_header = "INC-2024-0001 — Redis OOM"

    # Two sibling chunks — same section_header and source_document
    _make_chunk(
        db_session,
        source_document="runbook.md",
        chunk_index=0,
        content="Redis OOM root cause: TTL too long.",
        section_header=section_header,
        section_content=section_content,
    )
    _make_chunk(
        db_session,
        source_document="runbook.md",
        chunk_index=1,
        content="Fix Redis OOM: set allkeys-lru eviction policy.",
        section_header=section_header,
        section_content=section_content,
    )
    db_session.flush()

    query_embedding = embed_text("Redis eviction policy fix")
    results = find_similar_runbook_chunks(db_session, query_embedding, "Redis eviction policy fix", limit=5)

    # Both match, but dedup should collapse to one result
    matching = [r for r in results if r["chunk"].section_header == section_header]
    assert len(matching) == 1, f"Expected 1 deduplicated result, got {len(matching)}"


@pytest.mark.unit
def test_deduplication_limit_respected(db_session):
    """Result count does not exceed limit after deduplication."""
    # Create 3 chunks each from a different section
    for i in range(3):
        _make_chunk(
            db_session,
            source_document="runbook.md",
            chunk_index=i,
            content=f"Content for section {i} about Redis failures and fixes.",
            section_header=f"Section {i}",
            section_content=f"Full content for section {i}.",
        )
    db_session.flush()

    query_embedding = embed_text("Redis failures")
    results = find_similar_runbook_chunks(db_session, query_embedding, "Redis failures", limit=2)

    assert len(results) <= 2


@pytest.mark.unit
def test_deduplication_legacy_null_section_header(db_session):
    """Legacy chunks with section_header=NULL are grouped by source_document.

    Forces the Jaccard fallback path (patching HAS_PGVECTOR=False) so we can
    guarantee both chunks appear in candidates before deduplication, making the
    assertion non-vacuous.
    """
    from unittest.mock import patch

    _make_chunk(
        db_session,
        source_document="legacy.md",
        chunk_index=0,
        content="database connection pool exhaustion emergency fix procedure",
        section_header=None,
        section_content=None,
    )
    chunk_b = _make_chunk(
        db_session,
        source_document="legacy.md",
        chunk_index=1,
        content="database connection pool size configuration settings guide",
        section_header=None,
        section_content=None,
    )
    chunk_b.section_content = None
    db_session.flush()

    query_embedding = embed_text("database connection pool")
    # Force Jaccard path so both chunks are evaluated regardless of vector index
    with patch("app.services.incident_similarity.HAS_PGVECTOR", False):
        results = find_similar_runbook_chunks(
            db_session, query_embedding, "database connection pool", limit=5
        )

    legacy_results = [r for r in results if r["chunk"].source_document == "legacy.md"]
    assert len(legacy_results) == 1, "Legacy chunks from same doc should deduplicate to one"
```

- [ ] **Step 1b: Add Jaccard fallback test to same file**

Append to `tests/backend/unit/test_incident_similarity.py`:

```python
@pytest.mark.unit
def test_jaccard_fallback_context_key_and_dedup(db_session):
    """Jaccard fallback path returns context key and deduplicates sibling chunks.

    Patches HAS_PGVECTOR=False to force the Jaccard branch regardless of whether
    pgvector is installed in the test environment.
    """
    from unittest.mock import patch

    section_content = "Full incident: connection pool exhaustion root cause and resolution steps."
    section_header = "INC-Connection-Pool-Exhaustion"

    _make_chunk(
        db_session,
        source_document="runbook.md",
        chunk_index=10,
        content="connection pool exhaustion fix: increase max_connections",
        section_header=section_header,
        section_content=section_content,
    )
    _make_chunk(
        db_session,
        source_document="runbook.md",
        chunk_index=11,
        content="connection pool root cause: leaked connections in worker threads",
        section_header=section_header,
        section_content=section_content,
    )
    db_session.flush()

    query_embedding = embed_text("connection pool exhaustion")
    with patch("app.services.incident_similarity.HAS_PGVECTOR", False):
        results = find_similar_runbook_chunks(
            db_session, query_embedding, "connection pool exhaustion", limit=5
        )

    assert results, "Jaccard fallback should return results"
    assert "context" in results[0], "context key must be present in Jaccard fallback results"

    matching = [r for r in results if r["chunk"].section_header == section_header]
    assert len(matching) == 1, "Jaccard fallback must deduplicate sibling chunks to one result"
    assert matching[0]["context"] == section_content
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/felix/incident-triage
pytest tests/backend/unit/test_incident_similarity.py -v 2>&1 | tail -20
```

Expected: tests fail — no `context` key, no deduplication yet.

### 4b — Update `find_similar_runbook_chunks()`

- [ ] **Step 3: Update `incident_similarity.py`**

Add a deduplication helper after the existing `_rerank_boost` function (after line 91):

```python
def _dedup_by_section(
    ranked: List[Tuple[RunbookChunk, float]]
) -> List[Tuple[RunbookChunk, float]]:
    """
    Keep only the highest-scoring chunk per (source_document, section_header) group.
    Chunks with section_header=None are grouped by source_document alone.
    """
    best: dict = {}
    for chunk, score in ranked:
        key = (chunk.source_document, chunk.section_header)
        if key not in best or score > best[key][1]:
            best[key] = (chunk, score)
    return list(best.values())
```

Then in `find_similar_runbook_chunks()`, make three targeted changes:

**Change 1** — Inflate the DB query limits from `limit` to `limit * 3`. In the pgvector query (around line 228):
```python
# Before
.limit(limit)

# After
.limit(limit * 3)
```

In the BM25 query (around line 254):
```python
# Before
.limit(limit)

# After
.limit(limit * 3)
```

**Change 2** — After building `ranked`, deduplicate and trim before building results. Replace the final block (around lines 281–291):
```python
ranked.sort(key=lambda item: item[1], reverse=True)
ranked = _dedup_by_section(ranked)
ranked.sort(key=lambda item: item[1], reverse=True)

for chunk, score in ranked[:limit]:
    results.append({
        "chunk": chunk,
        "score": score,
        "context": chunk.section_content or chunk.content,
    })
```

**Change 3** — Update the Jaccard fallback path's `_rerank_boost` call and result dict (around lines 267–277):
```python
# Before
score += _rerank_boost(query_text, chunk.title, chunk.content)
...
matches.append((chunk, score))
...
for chunk, score in matches[:limit]:
    results.append({"chunk": chunk, "score": score})

# After
score += _rerank_boost(query_text, chunk.section_header or chunk.title, chunk.content)
...
matches.append((chunk, score))
...
matches.sort(key=lambda item: item[1], reverse=True)
matches = _dedup_by_section(matches)
matches.sort(key=lambda item: item[1], reverse=True)
for chunk, score in matches[:limit]:
    results.append({
        "chunk": chunk,
        "score": score,
        "context": chunk.section_content or chunk.content,
    })
```

- [ ] **Step 4: Run retrieval tests — expect pass**

```bash
cd /Users/felix/incident-triage
pytest tests/backend/unit/test_incident_similarity.py -v 2>&1 | tail -20
```

Expected: all 5 tests pass.

- [ ] **Step 5: Run full unit suite**

```bash
cd /Users/felix/incident-triage
pytest tests/backend/unit/ -v 2>&1 | tail -30
```

Expected: all tests pass. If `test_incident_summaries.py` fails because it passes a result dict without a `context` key, update that test to include `"context": chunk.content` in the dict passed to `generate_summary`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/incident_similarity.py tests/backend/unit/test_incident_similarity.py
git commit -m "feat(retrieval): deduplicate by section, add context key to runbook results"
```

---

## Task 5: Final verification

- [ ] **Step 1: Run the full unit test suite**

```bash
cd /Users/felix/incident-triage
pytest tests/backend/unit/ -v 2>&1 | tail -40
```

Expected: all tests pass, no failures.

- [ ] **Step 2: Smoke-test ingestion against a real notion mock file**

```bash
cd /Users/felix/incident-triage/backend
python - <<'EOF'
import sys
sys.path.insert(0, ".")
from app.services.ingestion import chunk_markdown_structured
from pathlib import Path

text = Path("../datasets/notion_mock/auth-sessions-runbook.md").read_text()
chunks = chunk_markdown_structured(text)
print(f"Total chunks: {len(chunks)}")
sections = {}
for c in chunks:
    sections.setdefault(c.section_header, []).append(c)
print(f"Unique sections: {len(sections)}")
for header, cs in list(sections.items())[:5]:
    print(f"  [{len(cs)} chunks] {header!r} — section_content len={len(cs[0].section_content)}")
EOF
```

Expected: total chunks in the range 30–80, multiple unique sections, each section_content meaningfully larger than the individual content field.

- [ ] **Step 3: Final commit (if any cleanup needed)**

```bash
git add -p  # review any remaining unstaged changes
git commit -m "chore: parent-doc retrieval cleanup"
```

---

## Spec reference

`docs/superpowers/specs/2026-03-21-parent-doc-retrieval-design.md`
