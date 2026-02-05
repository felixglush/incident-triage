"""
Similarity search helpers for incidents and runbooks.

Designed to be hybrid-ready: vector similarity when available, with
token overlap fallback. This keeps Phase 3 deterministic and simple,
while leaving room for future BM25 + vector hybrid retrieval.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from sqlalchemy import desc, func

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


VECTOR_WEIGHT = float(os.getenv("RAG_VECTOR_WEIGHT", "0.7"))
KEYWORD_WEIGHT = float(os.getenv("RAG_KEYWORD_WEIGHT", "0.3"))
MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.1"))
MIN_KEYWORD_OVERLAP = float(os.getenv("RAG_MIN_KEYWORD_OVERLAP", "0.05"))
RERANK_TITLE_BOOST = float(os.getenv("RAG_RERANK_TITLE_BOOST", "0.08"))
RERANK_PHRASE_BOOST = float(os.getenv("RAG_RERANK_PHRASE_BOOST", "0.05"))


def _hybrid_score(vector_score: float, keyword_score: float) -> float:
    return (vector_score * VECTOR_WEIGHT) + (keyword_score * KEYWORD_WEIGHT)


def _rerank_boost(query_text: str, title: str | None, content: str | None) -> float:
    if not query_text:
        return 0.0
    lowered = query_text.lower()
    boost = 0.0
    if title and lowered in title.lower():
        boost += RERANK_TITLE_BOOST
    if content and lowered in content.lower():
        boost += RERANK_PHRASE_BOOST
    return boost


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
    min_score: float = MIN_SCORE,
    min_keyword_overlap: float = MIN_KEYWORD_OVERLAP,
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
                candidate_text = build_incident_text(match, [])
                candidate_tokens = _tokens(candidate_text)
                candidate_services = set(match.affected_services or [])
                if not _passes_relevance(
                    query_tokens,
                    candidate_tokens,
                    query_services,
                    candidate_services,
                    min_token_overlap=min_keyword_overlap,
                ):
                    continue
                vector_score = _similarity_score_from_distance(dist)
                keyword_score = jaccard_similarity(query_tokens, candidate_tokens)
                score = _hybrid_score(vector_score, keyword_score)
                score += _rerank_boost(build_incident_text(incident, alerts), match.title, match.summary)
                score += _structured_boost(incident, match)
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
            min_token_overlap=min_keyword_overlap,
        ):
            continue
        keyword_score = jaccard_similarity(query_tokens, candidate_tokens)
        score = _hybrid_score(0.0, keyword_score)
        score += _rerank_boost(build_incident_text(incident, alerts), candidate.title, candidate.summary)
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
    min_score: float = MIN_SCORE,
) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    candidates: Dict[int, Dict[str, Any]] = {}

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
                entry = candidates.setdefault(chunk.id, {"chunk": chunk, "vector_score": 0.0, "bm25_score": 0.0})
                entry["vector_score"] = _similarity_score_from_distance(dist)
        except Exception:
            pass

    try:
        ts_query = func.plainto_tsquery("english", query_text)
        bm25_rows = (
            db.query(RunbookChunk, func.ts_rank_cd(RunbookChunk.search_tsv, ts_query).label("bm25_score"))
            .filter(RunbookChunk.search_tsv.isnot(None), RunbookChunk.source == "runbooks")
            .order_by(desc("bm25_score"))
            .limit(limit)
            .all()
        )
        for chunk, bm25_score in bm25_rows:
            entry = candidates.setdefault(chunk.id, {"chunk": chunk, "vector_score": 0.0, "bm25_score": 0.0})
            entry["bm25_score"] = float(bm25_score or 0.0)
    except Exception:
        bm25_rows = []

    if not candidates:
        matches: List[Tuple[RunbookChunk, float]] = []
        for chunk in db.query(RunbookChunk).filter(RunbookChunk.source == "runbooks").all():
            chunk_text = " ".join([chunk.title or "", chunk.content or ""]).strip()
            keyword_score = jaccard_similarity(_tokens(query_text), _tokens(chunk_text))
            score = _hybrid_score(0.0, keyword_score)
            score += _rerank_boost(query_text, chunk.title, chunk.content)
            if score < min_score:
                continue
            matches.append((chunk, score))

        matches.sort(key=lambda item: item[1], reverse=True)
        for chunk, score in matches[:limit]:
            results.append({"chunk": chunk, "score": score})
        return results

    ranked: List[Tuple[RunbookChunk, float]] = []
    for entry in candidates.values():
        chunk = entry["chunk"]
        score = _hybrid_score(entry["vector_score"], entry["bm25_score"])
        score += _rerank_boost(query_text, chunk.title, chunk.content)
        if score < min_score:
            continue
        ranked.append((chunk, min(score, 1.0)))

    ranked.sort(key=lambda item: item[1], reverse=True)
    for chunk, score in ranked[:limit]:
        results.append({"chunk": chunk, "score": score})

    return results
