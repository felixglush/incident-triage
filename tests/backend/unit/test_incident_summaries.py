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
