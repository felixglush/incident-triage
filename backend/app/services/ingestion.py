from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import RunbookChunk, SourceDocument
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


def upsert_markdown_document(
    db: Session,
    *,
    source_document: str,
    source: str,
    source_uri: Optional[str],
    content: str,
    tags: Optional[Iterable[str]] = None,
    extra_metadata: Optional[dict] = None,
) -> int:
    tags = list(tags or [])
    extra_metadata = dict(extra_metadata or {})
    version_hash = compute_hash(content)
    chunks = chunk_markdown(content)
    document_title = extra_metadata.get("title")
    if not document_title and chunks:
        document_title = chunks[0].title

    document_metadata = {
        "tags": tags,
        "source": source,
        **extra_metadata,
    }

    existing_document = (
        db.query(SourceDocument)
        .filter(SourceDocument.source_document == source_document)
        .filter(SourceDocument.source == source)
        .first()
    )

    if existing_document:
        document_changed = (
            existing_document.version_hash != version_hash
            or existing_document.source_uri != source_uri
            or existing_document.title != document_title
            or (existing_document.doc_metadata or {}) != document_metadata
        )
    else:
        document_changed = True

    if existing_document and not document_changed:
        existing_chunk = (
            db.query(RunbookChunk)
            .filter(RunbookChunk.source_document == source_document)
            .filter(RunbookChunk.source == source)
            .first()
        )
        if existing_chunk and existing_chunk.doc_metadata and existing_chunk.doc_metadata.get("version_hash") == version_hash:
            return 0

    if existing_document:
        existing_document.source_uri = source_uri
        existing_document.title = document_title
        existing_document.content = content
        existing_document.version_hash = version_hash
        existing_document.doc_metadata = document_metadata
        db.add(existing_document)
    else:
        db.add(
            SourceDocument(
                source_document=source_document,
                source=source,
                source_uri=source_uri,
                title=document_title,
                content=content,
                version_hash=version_hash,
                doc_metadata=document_metadata,
            )
        )

    if not document_changed:
        return 0

    db.query(RunbookChunk).filter(
        RunbookChunk.source_document == source_document,
        RunbookChunk.source == source,
    ).delete()

    inserted = 0
    for chunk in chunks:
        metadata = {
            "tags": tags,
            "source": source,
            "version_hash": version_hash,
            "title": chunk.title,
            **extra_metadata,
        }
        search_text = f"{chunk.title or ''} {chunk.content}".strip()
        db.add(
            RunbookChunk(
                source_document=source_document,
                chunk_index=chunk.chunk_index,
                title=chunk.title,
                content=chunk.content,
                search_tsv=func.to_tsvector("english", search_text),
                embedding=embed_text(chunk.content),
                doc_metadata=metadata,
                source=source,
                source_uri=source_uri,
            )
        )
        inserted += 1

    return inserted


def delete_source_documents(
    db: Session,
    *,
    source: str,
    source_documents: Iterable[str],
) -> int:
    documents = {item for item in source_documents if item}
    if not documents:
        return 0

    deleted = (
        db.query(RunbookChunk)
        .filter(RunbookChunk.source == source)
        .filter(RunbookChunk.source_document.in_(documents))
        .delete(synchronize_session=False)
    )
    db.query(SourceDocument).filter(
        SourceDocument.source == source,
        SourceDocument.source_document.in_(documents),
    ).delete(synchronize_session=False)
    return deleted


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
        inserted += upsert_markdown_document(
            db,
            source_document=path.name,
            source=source,
            source_uri=str(path),
            content=content,
            tags=tags,
        )

    db.commit()
    return inserted
