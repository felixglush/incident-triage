#!/usr/bin/env python3
"""
Ingest markdown knowledge sources into the database.

Usage:
  python backend/tools/ingest_knowledge.py --path runbooks --source runbooks
  python backend/tools/ingest_knowledge.py --path datasets/notion_mock --source notion
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import get_db_context
from app.services.ingestion import ingest_folder


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest markdown knowledge sources")
    parser.add_argument("--path", required=True, help="Folder with .md files")
    parser.add_argument("--source", required=True, help="Source name (runbooks|notion)")
    parser.add_argument("--tag", action="append", default=[], help="Optional tag (repeatable)")
    args = parser.parse_args()

    folder = Path(args.path)
    if not folder.exists():
        raise SystemExit(f"Folder not found: {folder}")

    with get_db_context() as db:
        inserted = ingest_folder(db, folder, source=args.source, tags=args.tag)

    print(f"Inserted {inserted} chunks from {folder} ({args.source})")


if __name__ == "__main__":
    main()
