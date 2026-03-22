"""
Unit tests for find_similar_runbook_chunks() — deduplication, context key,
and limit inflation (Task 4).

All tests use MagicMock for the DB session; no real DB required.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.models import RunbookChunk
from app.services.incident_similarity import find_similar_runbook_chunks


def _make_chunk(
    id: int,
    source_document: str,
    title: str,
    content: str,
    section_header: str | None = None,
    section_content: str | None = None,
    embedding=None,
    search_tsv=None,
) -> RunbookChunk:
    chunk = RunbookChunk(
        id=id,
        source_document=source_document,
        chunk_index=id,
        title=title,
        content=content,
        source="runbooks",
        section_header=section_header,
        section_content=section_content,
    )
    chunk.embedding = embedding
    chunk.search_tsv = search_tsv
    return chunk


# ---------------------------------------------------------------------------
# Helpers to build a mock DB that returns controlled rows
# ---------------------------------------------------------------------------

def _mock_db_no_pgvector(chunks_with_scores):
    """Return a MagicMock db whose query chain yields (chunk, bm25_score) pairs."""
    db = MagicMock()
    # Make every chained call return the mock itself until .all()
    query_mock = MagicMock()
    db.query.return_value = query_mock
    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.limit.return_value = query_mock
    query_mock.all.return_value = chunks_with_scores
    return db


# ---------------------------------------------------------------------------
# Test 1: context key uses section_content when non-null
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_context_key_uses_section_content():
    """result["context"] should equal chunk.section_content when it is non-null."""
    section_text = "Full parent section text for the section."
    chunk = _make_chunk(
        id=1,
        source_document="runbook-a.md",
        title="Runbook A",
        content="Sub-chunk content only.",
        section_header="Section Header A",
        section_content=section_text,
    )

    db = _mock_db_no_pgvector([(chunk, 0.5)])

    with patch("app.services.incident_similarity.HAS_PGVECTOR", False):
        results = find_similar_runbook_chunks(
            db=db,
            query_embedding=[0.1] * 384,
            query_text="runbook section content",
            limit=5,
            min_score=0.0,
        )

    assert len(results) == 1
    assert results[0]["context"] == section_text


# ---------------------------------------------------------------------------
# Test 2: context key falls back to chunk.content when section_content is None
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_context_key_falls_back_to_content_when_section_content_null():
    """result["context"] should equal chunk.content when section_content is None."""
    chunk = _make_chunk(
        id=2,
        source_document="legacy-runbook.md",
        title="Legacy Runbook",
        content="Legacy chunk content with no section.",
        section_header=None,
        section_content=None,
    )

    db = _mock_db_no_pgvector([(chunk, 0.5)])

    with patch("app.services.incident_similarity.HAS_PGVECTOR", False):
        results = find_similar_runbook_chunks(
            db=db,
            query_embedding=[0.1] * 384,
            query_text="legacy runbook content",
            limit=5,
            min_score=0.0,
        )

    assert len(results) == 1
    assert results[0]["context"] == chunk.content


# ---------------------------------------------------------------------------
# Test 3: deduplication collapses sibling chunks to one result
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_deduplication_collapses_siblings_to_one_result():
    """Two chunks with the same (source_document, section_header) should collapse to one."""
    section_header = "INC-2024-0156 — Redis OOM"
    section_content = "Full section content shared by both siblings."

    chunk_a = _make_chunk(
        id=10,
        source_document="auth-runbook.md",
        title="Auth Runbook",
        content="Description and root cause (~900 chars).",
        section_header=section_header,
        section_content=section_content,
    )
    chunk_b = _make_chunk(
        id=11,
        source_document="auth-runbook.md",
        title="Auth Runbook",
        content="Resolution steps 1-6 (~1100 chars).",
        section_header=section_header,
        section_content=section_content,
    )

    # chunk_b has a higher score — it should be the surviving entry
    db = _mock_db_no_pgvector([(chunk_a, 0.3), (chunk_b, 0.7)])

    with patch("app.services.incident_similarity.HAS_PGVECTOR", False):
        results = find_similar_runbook_chunks(
            db=db,
            query_embedding=[0.1] * 384,
            query_text="redis session store memory exhaustion fix",
            limit=5,
            min_score=0.0,
        )

    assert len(results) == 1
    # The surviving chunk must be the higher-scored one
    assert results[0]["chunk"].id == chunk_b.id


# ---------------------------------------------------------------------------
# Test 4: deduplication limit is respected
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_deduplication_limit_respected():
    """DB returns limit*3 raw candidates from 3 distinct sections; result is exactly limit=1."""
    # We'll use limit=1 and 3 distinct sections (3 chunks), so after dedup we get 3 unique
    # sections, then trim to limit=1.
    chunks = [
        _make_chunk(
            id=i,
            source_document=f"doc-{i}.md",
            title=f"Doc {i}",
            content=f"Content for doc {i}.",
            section_header=f"Section {i}",
            section_content=f"Full section {i} content.",
        )
        for i in range(3)
    ]

    db = _mock_db_no_pgvector([(c, 0.8 - i * 0.1) for i, c in enumerate(chunks)])

    with patch("app.services.incident_similarity.HAS_PGVECTOR", False):
        results = find_similar_runbook_chunks(
            db=db,
            query_embedding=[0.1] * 384,
            query_text="doc content section",
            limit=1,
            min_score=0.0,
        )

    assert len(results) == 1


# ---------------------------------------------------------------------------
# Test 5: legacy chunks (section_header=None) deduplicate by source_document alone
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_deduplication_legacy_null_section_header():
    """Chunks with section_header=None should deduplicate by source_document alone."""
    # Two legacy chunks from the same source_document (no section_header)
    chunk_x = _make_chunk(
        id=20,
        source_document="old-runbook.md",
        title="Old Runbook",
        content="First legacy chunk.",
        section_header=None,
        section_content=None,
    )
    chunk_y = _make_chunk(
        id=21,
        source_document="old-runbook.md",
        title="Old Runbook",
        content="Second legacy chunk with higher score.",
        section_header=None,
        section_content=None,
    )
    # A third chunk from a different document
    chunk_z = _make_chunk(
        id=22,
        source_document="other-runbook.md",
        title="Other Runbook",
        content="Chunk from a different document.",
        section_header=None,
        section_content=None,
    )

    db = _mock_db_no_pgvector([(chunk_x, 0.4), (chunk_y, 0.6), (chunk_z, 0.5)])

    with patch("app.services.incident_similarity.HAS_PGVECTOR", False):
        results = find_similar_runbook_chunks(
            db=db,
            query_embedding=[0.1] * 384,
            query_text="legacy runbook chunk content",
            limit=5,
            min_score=0.0,
        )

    # chunk_x and chunk_y should collapse to one (highest score = chunk_y); chunk_z stays
    assert len(results) == 2
    surviving_ids = {r["chunk"].id for r in results}
    assert 21 in surviving_ids   # chunk_y (higher score)
    assert 20 not in surviving_ids  # chunk_x deduplicated away
    assert 22 in surviving_ids   # chunk_z from different doc


# ---------------------------------------------------------------------------
# Test 6: Jaccard fallback path has context key and dedup
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_jaccard_fallback_context_key_and_dedup():
    """In the Jaccard fallback (HAS_PGVECTOR=False, candidates dict is empty),
    results must have 'context' key and deduplication must work."""
    section_content = "Full section text for fallback test."
    chunk_a = _make_chunk(
        id=30,
        source_document="fallback-runbook.md",
        title="Fallback Runbook",
        content="jaccard fallback content first chunk",
        section_header="Fallback Section",
        section_content=section_content,
    )
    chunk_b = _make_chunk(
        id=31,
        source_document="fallback-runbook.md",
        title="Fallback Runbook",
        content="jaccard fallback content second chunk",
        section_header="Fallback Section",
        section_content=section_content,
    )

    db = MagicMock()
    # The Jaccard path calls db.query(RunbookChunk).filter(...).all()
    query_mock = MagicMock()
    db.query.return_value = query_mock
    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.limit.return_value = query_mock
    query_mock.all.return_value = [chunk_a, chunk_b]

    with patch("app.services.incident_similarity.HAS_PGVECTOR", False):
        # Also patch the bm25/vector paths to force Jaccard: ensure candidates stays empty
        # by making every DB call return empty for the vector/bm25 paths but populated for
        # the Jaccard path. We do this by controlling what .all() returns on different calls.
        call_count = {"n": 0}
        original_all = query_mock.all

        def side_effect_all():
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call: BM25 path — return empty to force Jaccard fallback
                return []
            # Second call: Jaccard path
            return [chunk_a, chunk_b]

        query_mock.all.side_effect = side_effect_all

        results = find_similar_runbook_chunks(
            db=db,
            query_embedding=[0.1] * 384,
            query_text="jaccard fallback content chunk",
            limit=5,
            min_score=0.0,
        )

    # All results must have "context" key
    for r in results:
        assert "context" in r

    # Siblings should have been deduplicated to one result
    assert len(results) == 1
    assert results[0]["context"] == section_content
