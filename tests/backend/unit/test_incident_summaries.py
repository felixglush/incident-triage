import pytest
from unittest.mock import patch, MagicMock

from app.models import Incident, RunbookChunk, SeverityLevel, IncidentStatus
from app.services.incident_summaries import generate_summary


def test_generate_summary_includes_runbook_title_and_source_uri():
    incident = Incident(
        id=1,
        title="Queue backlog",
        severity=SeverityLevel.ERROR,
        status=IncidentStatus.OPEN,
    )
    chunk = RunbookChunk(
        source_document="queue-runbook.md",
        chunk_index=0,
        title="Queue Troubleshooting",
        content="Queue depth high in production. Check worker health.",
        source="notion",
        source_uri="https://www.notion.so/queue-troubleshooting",
    )

    _summary, citations = generate_summary(
        incident,
        alerts=[],
        similar_incidents=[],
        runbook_chunks=[{"chunk": chunk, "score": 0.91}],
    )

    assert citations == [
        {
            "type": "runbook",
            "source_document": "queue-runbook.md",
            "chunk_index": 0,
            "title": "Queue Troubleshooting",
            "source_uri": "https://www.notion.so/queue-troubleshooting",
            "score": 0.91,
        }
    ]


# ---------------------------------------------------------------------------
# Test: embed_text failure in summarize_incident falls back to BM25
# ---------------------------------------------------------------------------

@pytest.mark.unit
@pytest.mark.database
@pytest.mark.no_embed_patch
def test_summarize_incident_embedding_failure_falls_back_to_bm25(db_session):
    """When embed_text raises RuntimeError in summarize_incident, query_embedding
    must be None so find_similar_runbook_chunks uses BM25-only retrieval."""
    from app.services.incident_summaries import summarize_incident

    incident = Incident(
        title="Redis OOM",
        severity=SeverityLevel.CRITICAL,
        status=IncidentStatus.OPEN,
        affected_services=["redis"],
    )
    db_session.add(incident)
    db_session.flush()

    with patch("app.services.incident_summaries.embed_text",
               side_effect=RuntimeError("ML service unavailable")), \
         patch("app.services.incident_summaries.ensure_incident_embedding"), \
         patch("app.services.incident_summaries.ensure_runbook_embeddings"), \
         patch("app.services.incident_summaries.find_similar_incidents",
               return_value=[]), \
         patch("app.services.incident_summaries.find_similar_runbook_chunks",
               return_value=[]) as mock_find, \
         patch("app.services.incident_summaries.generate_summary",
               return_value=("summary text", [])), \
         patch("app.services.incident_summaries._build_next_steps",
               return_value=[]):
        summarize_incident(db_session, incident.id)

    assert mock_find.called
    actual_embedding = mock_find.call_args[0][1]
    assert actual_embedding is None, (
        f"Expected query_embedding=None when embed_text fails, got {actual_embedding!r}"
    )
