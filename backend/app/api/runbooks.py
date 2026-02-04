from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import RunbookChunk

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
            }
        else:
            if updated_at and (not entry["updated_at"] or updated_at > entry["updated_at"]):
                entry["updated_at"] = updated_at
            for tag in tags:
                if tag not in entry["tags"]:
                    entry["tags"].append(tag)

    items = []
    for index, entry in enumerate(sorted(runbooks.values(), key=lambda item: item["source_document"]), start=1):
        items.append({
            "id": f"RB-{index:03d}",
            "title": entry["title"],
            "source": entry["source_document"],
            "tags": entry["tags"],
            "last_updated": entry["updated_at"].isoformat() if entry["updated_at"] else None,
        })

    return items


@router.get("")
def list_runbooks(limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    chunks = (
        db.query(RunbookChunk)
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
