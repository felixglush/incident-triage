from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import RunbookChunk, SourceDocument
from app.services.embeddings import embed_text


@dataclass
class DocumentChunk:
    content: str
    chunk_index: int
    title: Optional[str] = None
    section_header: Optional[str] = None  # H2/H3 header text for this section
    section_content: Optional[str] = None  # Full parent section text


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_title(lines: list[str]) -> Optional[str]:
    for line in lines:
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return None


def _extract_sections(text: str, title: Optional[str]) -> List[Tuple[Optional[str], str]]:
    """
    Split markdown text into (section_header, section_content) pairs on ## / ### boundaries.
    Content before the first ## or ### header becomes a preamble attributed to the document title.
    Returns list of (header: str | None, content: str) tuples, skipping empty sections.
    """
    lines = text.splitlines()
    sections: List[Tuple[Optional[str], str]] = []
    current_header: Optional[str] = title
    current_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        is_boundary = stripped.startswith("## ") or stripped.startswith("### ")
        if is_boundary:
            content = "\n".join(current_lines).strip()
            if content:
                sections.append((current_header, content))
            current_header = stripped.lstrip("#").strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    content = "\n".join(current_lines).strip()
    if content:
        sections.append((current_header, content))

    # Filter out thin sections that contain only a header line (no real content).
    # This happens when a ## section immediately precedes ### sub-sections with no
    # body text of its own — emitting a one-line chunk would pollute the index.
    return [
        (h, c) for h, c in sections
        if c and len(c.splitlines()) > 1
    ]


def _split_section(text: str, max_chars: int, overlap: int) -> List[str]:
    """
    Split section text into sub-chunks by paragraph boundaries (blank lines).
    Overlap is applied only within the section — never across section boundaries.
    A single paragraph larger than max_chars becomes its own chunk unsplit.
    Returns at least one element (the full text if no blank lines found).
    """
    lines = text.splitlines()
    paragraphs: List[str] = []
    buffer: List[str] = []

    for line in lines:
        if line.strip() == "" and buffer:
            paragraphs.append("\n".join(buffer).strip())
            buffer = []
        else:
            buffer.append(line)
    if buffer:
        paragraphs.append("\n".join(buffer).strip())

    sub_chunks: List[str] = []
    current = ""

    for para in paragraphs:
        if not para:
            continue
        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}".strip()
        else:
            if current.strip():
                sub_chunks.append(current.strip())
            current = para

    if current.strip():
        sub_chunks.append(current.strip())

    # Apply within-section overlap only. Snapshot originals first to prevent
    # cascade: each chunk's overlap prefix must come from the prior chunk's
    # original content, not from its already-prepended overlap text.
    if overlap > 0 and len(sub_chunks) > 1:
        originals = list(sub_chunks)
        for i in range(1, len(sub_chunks)):
            overlap_text = originals[i - 1][-overlap:]
            sub_chunks[i] = f"{overlap_text}\n{sub_chunks[i]}"

    return sub_chunks if sub_chunks else [text.strip()]


def chunk_markdown_structured(
    text: str, max_chars: int = 1000, overlap: int = 150
) -> List[DocumentChunk]:
    """
    Structure-aware chunker. Splits on ## / ### header boundaries first,
    then sub-splits each section by paragraph into <= max_chars child chunks.

    Each child chunk carries:
      - content:         small sub-chunk text for embedding/indexing
      - section_header:  H2/H3 header of the parent section (for citations)
      - section_content: full parent section text (for LLM context — the "big" in small-to-big)
      - title:           document H1 title
      - chunk_index:     global sequential index across all sections

    Flat-doc fallback: if no ## or ### headers exist, the entire document is
    treated as one section (section_content = full document).
    """
    if not text or not text.strip():
        return []

    lines = text.splitlines()
    title = extract_title(lines)

    has_headers = any(
        l.strip().startswith("## ") or l.strip().startswith("### ") for l in lines
    )

    if has_headers:
        sections = _extract_sections(text, title)
    else:
        sections = [(title, text.strip())]

    chunks: List[DocumentChunk] = []

    for section_header, section_content in sections:
        sub_chunks = _split_section(section_content, max_chars, overlap)
        for sub_content in sub_chunks:
            chunks.append(
                DocumentChunk(
                    content=sub_content,
                    chunk_index=len(chunks),
                    title=title,
                    section_header=section_header,
                    section_content=section_content,
                )
            )

        if len(section_content) > 6000:
            logging.getLogger(__name__).warning(
                "Large section_content (%d chars) for section_header=%r — "
                "consider splitting this section",
                len(section_content),
                section_header,
            )

    return chunks


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
    chunks = chunk_markdown_structured(content)
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
        search_text = " ".join(filter(None, [chunk.section_header, chunk.title, chunk.content])).strip()
        db.add(
            RunbookChunk(
                source_document=source_document,
                chunk_index=chunk.chunk_index,
                title=chunk.title,
                content=chunk.content,
                section_header=chunk.section_header,      # NEW
                section_content=chunk.section_content,    # NEW
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
