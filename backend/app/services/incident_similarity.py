"""
Similarity search helpers for incidents and runbooks.

Designed to be hybrid-ready: vector similarity when available, with
token overlap fallback. This keeps Phase 3 deterministic and simple,
while leaving room for future BM25 + vector hybrid retrieval.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.models import Alert, Incident, RunbookChunk
from app.models.database import HAS_PGVECTOR
from app.services.embeddings import embed_text, jaccard_similarity, _tokens


def build_incident_text(incident: Incident, alerts: List[Alert]) -> str:
    parts = [incident.title or ""]
    if incident.summary:
        parts.append(incident.summary)
    if incident.affected_services:
        parts.append("services: " + ", ".join(incident.affected_services))

    for alert in alerts[:5]:
        if alert.title:
            parts.append(alert.title)
        if alert.message:
            parts.append(alert.message)

    return "\n".join(p for p in parts if p)


def ensure_incident_embedding(db: Session, incident: Incident, alerts: List[Alert]) -> List[float]:
    text = build_incident_text(incident, alerts)
    embedding = embed_text(text)
    incident.incident_embedding = embedding
    db.add(incident)
    return embedding


def ensure_runbook_embeddings(db: Session) -> None:
    chunks = db.query(RunbookChunk).filter(
        RunbookChunk.embedding.is_(None),
        RunbookChunk.source == "runbooks",
    ).all()
    for chunk in chunks:
        text = " ".join([chunk.title or "", chunk.content or ""]).strip()
        chunk.embedding = embed_text(text)
        db.add(chunk)


def _similarity_score_from_distance(distance: float) -> float:
    return 1.0 / (1.0 + float(distance))


def _structured_boost(query: Incident, candidate: Incident) -> float:
    boost = 0.0
    if query.severity == candidate.severity:
        boost += 0.05

    query_services = set(query.affected_services or [])
    candidate_services = set(candidate.affected_services or [])
    if query_services and candidate_services and query_services.intersection(candidate_services):
        boost += 0.1

    return boost


def _passes_relevance(
    query_tokens: List[str],
    candidate_tokens: List[str],
    query_services: set,
    candidate_services: set,
    min_token_overlap: float = 0.05,
) -> bool:
    if query_services and candidate_services and query_services.intersection(candidate_services):
        return True
    overlap = jaccard_similarity(query_tokens, candidate_tokens)
    return overlap >= min_token_overlap


def find_similar_incidents(
    db: Session,
    incident: Incident,
    alerts: List[Alert],
    limit: int = 5,
    min_score: float = 0.1,
) -> List[Dict[str, Any]]:
    query_embedding = incident.incident_embedding
    if query_embedding is None:
        query_embedding = ensure_incident_embedding(db, incident, alerts)

    results: List[Dict[str, Any]] = []
    query_tokens = _tokens(build_incident_text(incident, alerts))
    query_services = set(incident.affected_services or [])

    if HAS_PGVECTOR:
        try:
            distance = Incident.incident_embedding.l2_distance(query_embedding)
            rows = (
                db.query(Incident, distance.label("distance"))
                .filter(Incident.id != incident.id)
                .filter(Incident.incident_embedding.isnot(None))
                .order_by(distance.asc())
                .limit(limit)
                .all()
            )
            for match, dist in rows:
                candidate_tokens = _tokens(build_incident_text(match, []))
                candidate_services = set(match.affected_services or [])
                if not _passes_relevance(
                    query_tokens,
                    candidate_tokens,
                    query_services,
                    candidate_services,
                ):
                    continue
                score = _similarity_score_from_distance(dist) + _structured_boost(incident, match)
                score = min(score, 1.0)
                if score >= min_score:
                    results.append({
                        "incident": match,
                        "score": score,
                    })
            if results:
                return results
        except Exception:
            # Fall back to token overlap if vector search is unavailable
            results = []

    # Fallback: Jaccard similarity on tokens
    matches = []
    for candidate in db.query(Incident).filter(Incident.id != incident.id).all():
        candidate_text = build_incident_text(candidate, [])
        candidate_tokens = _tokens(candidate_text)
        candidate_services = set(candidate.affected_services or [])
        if not _passes_relevance(
            query_tokens,
            candidate_tokens,
            query_services,
            candidate_services,
        ):
            continue
        score = jaccard_similarity(query_tokens, candidate_tokens)
        score += _structured_boost(incident, candidate)
        score = min(score, 1.0)
        if score >= min_score:
            matches.append((candidate, score))

    matches.sort(key=lambda item: item[1], reverse=True)
    for match, score in matches[:limit]:
        results.append({"incident": match, "score": score})

    return results


def find_similar_runbook_chunks(
    db: Session,
    query_embedding: List[float],
    query_text: str,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    if HAS_PGVECTOR:
        try:
            distance = RunbookChunk.embedding.l2_distance(query_embedding)
            rows = (
                db.query(RunbookChunk, distance.label("distance"))
                .filter(RunbookChunk.embedding.isnot(None), RunbookChunk.source == "runbooks")
                .order_by(distance.asc())
                .limit(limit)
                .all()
            )
            for chunk, dist in rows:
                results.append({
                    "chunk": chunk,
                    "score": _similarity_score_from_distance(dist),
                })
            if results:
                return results
        except Exception:
            results = []

    # Fallback: token overlap
    query_tokens = _tokens(query_text)
    matches: List[Tuple[RunbookChunk, float]] = []
    for chunk in db.query(RunbookChunk).filter(RunbookChunk.source == "runbooks").all():
        chunk_text = " ".join([chunk.title or "", chunk.content or ""]).strip()
        score = jaccard_similarity(query_tokens, _tokens(chunk_text))
        matches.append((chunk, score))

    matches.sort(key=lambda item: item[1], reverse=True)
    for chunk, score in matches[:limit]:
        results.append({"chunk": chunk, "score": score})

    return results
