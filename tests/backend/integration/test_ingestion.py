from pathlib import Path

import pytest

from app.models import RunbookChunk
from app.services.ingestion import ingest_folder


@pytest.mark.integration
def test_ingest_folder_inserts_chunks(tmp_path: Path, db_session):
    md = tmp_path / "sample.md"
    md.write_text("# Title\n\nBody paragraph.\n\nMore text.", encoding="utf-8")

    inserted = ingest_folder(db_session, tmp_path, source="runbooks", tags=["test"])
    assert inserted > 0

    chunks = db_session.query(RunbookChunk).filter(RunbookChunk.source_document == "sample.md").all()
    assert len(chunks) > 0
    assert chunks[0].source == "runbooks"
