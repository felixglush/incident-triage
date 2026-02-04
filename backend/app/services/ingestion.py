from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from app.models import RunbookChunk
from app.services.embeddings import embed_text


@dataclass
class DocumentChunk:
    content: str
    chunk_index: int
    title: Optional[str] = None


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_title(lines: list[str]) -> Optional[str]:
    for line in lines:
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return None


def chunk_markdown(text: str, max_chars: int = 2400, overlap: int = 200) -> List[DocumentChunk]:
    lines = text.splitlines()
    title = extract_title(lines)
    paragraphs: list[str] = []
    buffer: list[str] = []

    for line in lines:
        if line.strip() == "" and buffer:
            paragraphs.append("\n".join(buffer).strip())
            buffer = []
        else:
            buffer.append(line)
    if buffer:
        paragraphs.append("\n".join(buffer).strip())

    chunks: list[DocumentChunk] = []
    current = ""

    def flush():
        nonlocal current
        if current.strip():
            chunks.append(DocumentChunk(content=current.strip(), chunk_index=len(chunks), title=title))
        current = ""

    for para in paragraphs:
        if not para:
            continue
        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}".strip()
        else:
            flush()
            current = para

    flush()

    if overlap > 0 and len(chunks) > 1:
        for idx in range(1, len(chunks)):
            prev = chunks[idx - 1].content
            overlap_text = prev[-overlap:]
            chunks[idx].content = f"{overlap_text}\n{chunks[idx].content}"

    return chunks


def ingest_folder(
    db: Session,
    folder: Path,
    source: str,
    tags: Optional[Iterable[str]] = None,
) -> int:
    tags = list(tags or [])
    inserted = 0
    for path in sorted(folder.glob("*.md")):
        if path.name.lower().startswith("readme"):
            continue
        content = path.read_text(encoding="utf-8")
        version_hash = compute_hash(content)
        chunks = chunk_markdown(content)

        existing = (
            db.query(RunbookChunk)
            .filter(RunbookChunk.source_document == path.name)
            .filter(RunbookChunk.source == source)
            .first()
        )
        if existing and existing.doc_metadata and existing.doc_metadata.get("version_hash") == version_hash:
            continue

        db.query(RunbookChunk).filter(
            RunbookChunk.source_document == path.name,
            RunbookChunk.source == source,
        ).delete()

        for chunk in chunks:
            metadata = {
                "tags": tags,
                "source": source,
                "version_hash": version_hash,
                "title": chunk.title,
            }
            db.add(
                RunbookChunk(
                    source_document=path.name,
                    chunk_index=chunk.chunk_index,
                    title=chunk.title,
                    content=chunk.content,
                    embedding=embed_text(chunk.content),
                    doc_metadata=metadata,
                    source=source,
                    source_uri=str(path),
                )
            )
            inserted += 1

    db.commit()
    return inserted
