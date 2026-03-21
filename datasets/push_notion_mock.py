#!/usr/bin/env python3
"""
Push mock Notion docs to a real Notion workspace.

Reads .md files from datasets/notion_mock/ and creates them as child pages
under a specified parent page using the Notion API.

Usage:
    python datasets/push_notion_mock.py
    python datasets/push_notion_mock.py --parent <page-id-or-url>
    python datasets/push_notion_mock.py --dry-run

Requirements:
    - NOTION_TOKEN in .env or environment
"""
import argparse
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = os.getenv("NOTION_API_VERSION", "2026-03-11")
MOCK_DIR = Path(__file__).parent / "notion_mock"
DEFAULT_PARENT = "32436ca4-e147-806f-a4b6-c042a6fa02ac"
NOTION_BLOCK_LIMIT = 100


def normalize_page_id(value: str) -> str:
    raw = re.findall(
        r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        value,
    )
    if not raw:
        raise ValueError(f"Could not parse a Notion page ID from: {value!r}")
    page_id = raw[-1].replace("-", "").lower()
    return f"{page_id[0:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:32]}"


def md_to_blocks(content: str) -> list:
    """Convert markdown text to a list of Notion block objects."""
    blocks = []
    for line in content.splitlines():
        stripped = line.rstrip()

        if stripped.startswith("### "):
            blocks.append(_heading(3, stripped[4:]))
        elif stripped.startswith("## "):
            blocks.append(_heading(2, stripped[3:]))
        elif stripped.startswith("# "):
            blocks.append(_heading(1, stripped[2:]))
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append(_bullet(stripped[2:]))
        elif stripped == "":
            continue
        else:
            blocks.append(_paragraph(stripped))

    return blocks


def _rich_text(text: str) -> list:
    return [{"type": "text", "text": {"content": text}}]


def _heading(level: int, text: str) -> dict:
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": _rich_text(text)}}


def _bullet(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": _rich_text(text)},
    }


def _paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text(text)},
    }


def create_page(session: requests.Session, parent_id: str, title: str, blocks: list) -> dict:
    payload = {
        "parent": {"type": "page_id", "page_id": parent_id},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
        },
        "children": blocks[:NOTION_BLOCK_LIMIT],
    }
    resp = session.post(f"{NOTION_API_BASE}/pages", json=payload, timeout=30)
    resp.raise_for_status()
    page = resp.json()

    if len(blocks) > NOTION_BLOCK_LIMIT:
        append_blocks(session, page["id"], blocks[NOTION_BLOCK_LIMIT:])

    return page


def append_blocks(session: requests.Session, block_id: str, blocks: list) -> None:
    """Append blocks to an existing Notion block in batches of 100."""
    for i in range(0, len(blocks), NOTION_BLOCK_LIMIT):
        batch = blocks[i : i + NOTION_BLOCK_LIMIT]
        resp = session.patch(
            f"{NOTION_API_BASE}/blocks/{block_id}/children",
            json={"children": batch},
            timeout=30,
        )
        resp.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description="Push mock Notion docs to Notion")
    parser.add_argument(
        "--parent",
        default=DEFAULT_PARENT,
        help="Parent page ID or URL (default: Runbooks page)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created without calling the API",
    )
    args = parser.parse_args()

    token = os.getenv("NOTION_TOKEN", "").strip()
    if not token:
        print("Error: NOTION_TOKEN is not set")
        sys.exit(1)

    try:
        parent_id = normalize_page_id(args.parent)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    md_files = sorted(MOCK_DIR.glob("*.md"))
    if not md_files:
        print(f"No .md files found in {MOCK_DIR}")
        sys.exit(1)

    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }
    )

    print(f"Parent page: {parent_id}")
    print(f"Files: {len(md_files)}\n")

    for md_file in md_files:
        content = md_file.read_text()
        title = md_file.stem.replace("-", " ").title()
        blocks = md_to_blocks(content)

        if args.dry_run:
            batches = (len(blocks) + NOTION_BLOCK_LIMIT - 1) // NOTION_BLOCK_LIMIT
            print(f"[dry-run] Would create: '{title}' ({len(blocks)} blocks, {batches} batch(es))")
            continue

        try:
            page = create_page(session, parent_id, title, blocks)
            page_url = page.get("url", "")
            print(f"  Created: '{title}' -> {page_url}")
        except requests.HTTPError as e:
            print(f"  Failed '{title}': {e.response.status_code} {e.response.text[:200]}")
            sys.exit(1)

    if not args.dry_run:
        print(f"\nDone. {len(md_files)} page(s) created under {parent_id}")


if __name__ == "__main__":
    main()
