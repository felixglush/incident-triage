from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import RunbookChunk
from app.services.embeddings import embed_text
from app.services.incident_similarity import ensure_runbook_embeddings, find_similar_runbook_chunks

router = APIRouter()


def build_runbook_index(chunks: list[RunbookChunk]) -> list[dict]:
    runbooks: dict[str, dict] = {}
    for chunk in chunks:
        key = chunk.source_document
        tags = []
        if isinstance(chunk.doc_metadata, dict):
            tags = chunk.doc_metadata.get("tags", []) or []

        entry = runbooks.get(key)
        updated_at = chunk.updated_at or chunk.created_at
        if not entry:
            runbooks[key] = {
                "source_document": key,
                "title": chunk.title or key,
                "tags": list(tags),
                "updated_at": updated_at,
                "source": chunk.source,
                "source_uri": chunk.source_uri,
            }
        else:
            if updated_at and (not entry["updated_at"] or updated_at > entry["updated_at"]):
                entry["updated_at"] = updated_at
            for tag in tags:
                if tag not in entry["tags"]:
                    entry["tags"].append(tag)
            if not entry.get("source"):
                entry["source"] = chunk.source
            if not entry.get("source_uri") and chunk.source_uri:
                entry["source_uri"] = chunk.source_uri

    items = []
    for index, entry in enumerate(sorted(runbooks.values(), key=lambda item: item["source_document"]), start=1):
        items.append({
            "id": f"RB-{index:03d}",
            "title": entry["title"],
            "source": entry["source_document"],
            "source_type": entry.get("source"),
            "source_uri": entry.get("source_uri"),
            "tags": entry["tags"],
            "last_updated": entry["updated_at"].isoformat() if entry["updated_at"] else None,
        })

    return items


@router.get("")
def list_runbooks(limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    chunks = (
        db.query(RunbookChunk)
        .filter(RunbookChunk.source == "runbooks")
        .order_by(RunbookChunk.source_document.asc(), RunbookChunk.chunk_index.asc())
        .all()
    )
    items = build_runbook_index(chunks)
    total = len(items)
    return {
        "items": items[offset: offset + limit],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/search")
def search_runbooks(
    q: str = Query(..., min_length=2),
    limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    ensure_runbook_embeddings(db)
    query_embedding = embed_text(q)
    matches = find_similar_runbook_chunks(db, query_embedding, q, limit=limit)
    items = []
    for match in matches:
        chunk = match["chunk"]
        items.append({
            "id": chunk.id,
            "score": match["score"],
            "source": chunk.source,
            "source_uri": chunk.source_uri,
            "source_document": chunk.source_document,
            "chunk_index": chunk.chunk_index,
            "title": chunk.title,
            "content": chunk.content,
            "metadata": chunk.doc_metadata or {},
        })
    return {
        "items": items,
        "total": len(items),
        "limit": limit,
        "query": q,
    }
