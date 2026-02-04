#!/usr/bin/env python3
"""
Watch a folder for markdown changes and re-ingest on updates.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import get_db_context
from app.services.ingestion import ingest_folder

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - optional dependency for dev
    FileSystemEventHandler = None
    Observer = None


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch runbooks folder for changes")
    parser.add_argument("--path", required=True, help="Folder with .md files")
    parser.add_argument("--source", default="runbooks", help="Source name")
    parser.add_argument("--interval", type=float, default=2.0, help="Polling interval seconds")
    args = parser.parse_args()

    folder = Path(args.path)
    if not folder.exists():
        raise SystemExit(f"Folder not found: {folder}")

    if Observer and FileSystemEventHandler:
        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                if event.is_directory:
                    return
                if not event.src_path.endswith(".md"):
                    return
                with get_db_context() as db:
                    ingest_folder(db, folder, source=args.source)
                print(f"Ingested changes from {folder}")

        observer = Observer()
        observer.schedule(Handler(), str(folder), recursive=False)
        observer.start()
        print(f"Watching {folder} for changes (source={args.source})...")
        try:
            observer.join()
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
    else:
        last_seen: dict[str, float] = {}
        print("watchdog not installed; falling back to polling.")
        print(f"Watching {folder} for changes (source={args.source})...")
        while True:
            changed = False
            for path in folder.glob("*.md"):
                mtime = path.stat().st_mtime
                if path.name not in last_seen or last_seen[path.name] < mtime:
                    last_seen[path.name] = mtime
                    changed = True

            if changed:
                with get_db_context() as db:
                    ingest_folder(db, folder, source=args.source)
                print(f"Ingested changes from {folder}")
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
