from app.services.ingestion import chunk_markdown


def test_chunk_markdown_splits_on_paragraphs():
    text = "# Title\n\nPara one.\n\nPara two.\n\nPara three."
    chunks = chunk_markdown(text, max_chars=20, overlap=0)
    assert len(chunks) >= 2
    assert chunks[0].content
    assert chunks[0].chunk_index == 0


def test_chunk_markdown_overlap():
    text = "# Title\n\nParagraph one.\n\nParagraph two."
    chunks = chunk_markdown(text, max_chars=30, overlap=5)
    assert len(chunks) >= 2
    assert chunks[1].content.startswith(chunks[0].content[-5:])


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
