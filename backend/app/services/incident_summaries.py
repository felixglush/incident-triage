"""
Incident summarization and next-step generation.
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models import Alert, Incident, SeverityLevel
from app.services.incident_similarity import (
    build_incident_text,
    ensure_incident_embedding,
    ensure_runbook_embeddings,
    find_similar_incidents,
    find_similar_runbook_chunks,
)


def _format_alert_highlights(alerts: List[Alert], limit: int = 3) -> List[str]:
    highlights = []
    for alert in alerts[:limit]:
        if alert.title:
            highlights.append(alert.title)
    return highlights


def _build_next_steps(
    incident: Incident,
    similar_incidents: List[Dict[str, Any]],
    runbook_chunks: List[Dict[str, Any]],
) -> List[str]:
    steps: List[str] = []

    if incident.severity in {SeverityLevel.CRITICAL, SeverityLevel.ERROR}:
        steps.append("Page on-call and open an incident bridge")

    if incident.affected_services:
        steps.append(f"Validate service health for: {', '.join(incident.affected_services)}")

    if similar_incidents:
        top = similar_incidents[0]["incident"]
        steps.append(f"Review similar incident #{top.id}: {top.title}")

    if runbook_chunks:
        chunk = runbook_chunks[0]["chunk"]
        steps.append(f"Check runbook: {chunk.source_document} (chunk {chunk.chunk_index})")

    if not steps:
        steps.append("Gather additional context from logs and metrics")

    return steps


def generate_summary(
    incident: Incident,
    alerts: List[Alert],
    similar_incidents: List[Dict[str, Any]],
    runbook_chunks: List[Dict[str, Any]],
) -> tuple[str, List[Dict[str, Any]]]:
    highlights = _format_alert_highlights(alerts)
    citations: List[Dict[str, Any]] = []

    summary_lines = [
        f"Incident #{incident.id} \"{incident.title}\" is {incident.status.value} with severity {incident.severity.value}.",
    ]

    if highlights:
        summary_lines.append("Key alerts: " + "; ".join(highlights))
        for alert in alerts[: min(len(alerts), 3)]:
            citations.append({
                "type": "alert",
                "id": alert.id,
                "title": alert.title,
            })

    if similar_incidents:
        summary_lines.append("Similar incidents:")
        for item in similar_incidents:
            match = item["incident"]
            score = round(item["score"], 3)
            summary_lines.append(f"- #{match.id} {match.title} (score {score})")
            citations.append({
                "type": "incident",
                "id": match.id,
                "title": match.title,
                "score": score,
            })

    if runbook_chunks:
        summary_lines.append("Relevant runbook references:")
        for item in runbook_chunks:
            chunk = item["chunk"]
            score = round(item["score"], 3)
            summary_lines.append(
                f"- {chunk.source_document} (chunk {chunk.chunk_index})"
            )
            citations.append({
                "type": "runbook",
                "source_document": chunk.source_document,
                "chunk_index": chunk.chunk_index,
                "title": chunk.title,
                "score": score,
            })

    return "\n".join(summary_lines), citations


def summarize_incident(
    db: Session,
    incident_id: int,
    limit_similar: int = 5,
    limit_runbook: int = 5,
) -> Dict[str, Any]:
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise ValueError("Incident not found")

    alerts = (
        db.query(Alert)
        .filter(Alert.incident_id == incident.id)
        .order_by(Alert.alert_timestamp.desc())
        .all()
    )

    # Ensure embeddings exist
    ensure_incident_embedding(db, incident, alerts)
    ensure_runbook_embeddings(db)
    db.flush()

    similar_incidents = find_similar_incidents(
        db,
        incident,
        alerts,
        limit=limit_similar,
    )

    query_text = build_incident_text(incident, alerts)
    runbook_chunks = find_similar_runbook_chunks(
        db,
        incident.incident_embedding,
        query_text,
        limit=limit_runbook,
    )

    summary, citations = generate_summary(
        incident,
        alerts,
        similar_incidents,
        runbook_chunks,
    )

    next_steps = _build_next_steps(incident, similar_incidents, runbook_chunks)

    incident.summary = summary
    incident.summary_citations = citations
    incident.next_steps = next_steps
    db.add(incident)
    db.commit()
    db.refresh(incident)

    return {
        "incident": incident,
        "similar_incidents": similar_incidents,
        "runbook_chunks": runbook_chunks,
        "summary": summary,
        "citations": citations,
        "next_steps": next_steps,
    }
