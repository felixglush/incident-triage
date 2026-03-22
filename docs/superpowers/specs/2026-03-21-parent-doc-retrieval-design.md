# Parent-Document Retrieval for RAG

**Date:** 2026-03-21
**Branch:** chunking-impl
**Status:** Approved

## Problem

The current `chunk_markdown()` splits documents purely on blank-line (paragraph) boundaries up to 2,400 chars, with 200-char trailing overlap. This causes two failures:

1. **Incident records get split mid-record.** A single H3 incident block (~100–150 lines, 2,000–4,500 chars) crosses the size ceiling and is cut arbitrarily — separating root cause from resolution steps.
2. **Embedding dilution.** Large chunks produce blurry vectors. A query about "how to fix Redis login failures" competes against metadata, impact figures, and follow-up tickets all embedded together.

The result: retrieval returns incomplete context and callers receive fragments instead of coherent incident records.

## Solution: Small-to-Big Retrieval

**Index small, retrieve big.**

- **Index unit:** Small sub-chunks (~1,000 chars) for precise vector matching
- **Context unit:** Full H3 section text (`section_content`) shared across all child chunks of that section — what callers use when injecting content into LLM prompts
- **Parent boundary:** H3 header (individual incident / procedure / checklist phase)

When a sub-chunk matches, the result dict carries the pre-stored full section — no reconstruction, no extra query, no joins.

### Concrete example

Ingesting `auth-sessions-runbook.md`, INC-2024-0156 (~4,200 chars) produces two child chunks:

| | Child chunk A | Child chunk B |
|---|---|---|
| `content` | Description + Root Cause + Impact (~900 chars) | Resolution Steps 1–6 + Follow-ups (~1,100 chars) |
| `embedding` | Vector of chunk A content | Vector of chunk B content |
| `section_header` | `"INC-2024-0156 — Redis Session Store Memory Exhaustion"` | same |
| `section_content` | Full 4,200-char H3 block (A + B stitched) | same |

Query: *"how do I fix Redis login failures?"*
→ Vector search matches chunk B (resolution steps)
→ Retrieval deduplicates by section: one result returned
→ `result["context"]` = `section_content` = the full incident record (A + B)

---

## Architecture

### Approach

**Approach 3: Full replacement with flat-doc fallback.**

Replace `chunk_markdown()` with `chunk_markdown_structured()`. The new function handles all document types — structured docs (with `##`/`###` headers) use header-aware splitting; flat docs (no headers) fall back to paragraph-based splitting, with `section_content` set to the full document text. No dead code, no dual code paths.

---

## Section 1: Ingestion & Chunking

### `DocumentChunk` dataclass

Two new optional fields:

```python
@dataclass
class DocumentChunk:
    content: str
    chunk_index: int
    title: Optional[str] = None
    section_header: Optional[str] = None   # NEW: H2/H3 header text
    section_content: Optional[str] = None  # NEW: full parent section text
```

### `chunk_markdown_structured()` — two-pass algorithm

**Pass 1: Section extraction**

Scan lines for `##` and `###` headers. Each header opens a new section. A section spans from its header line to the line before the next same-or-higher-level header (or end of document). Content before the first header becomes a preamble section attributed to the document title.

For each section:
- `section_header` = header text (e.g. `"INC-2024-0156 — Redis Session Store Memory Exhaustion"`)
- `section_content` = full raw text of that section (header line included)

**Pass 2: Sub-splitting**

Each section is sub-split into child chunks using paragraph-boundary splitting (existing logic), with `max_chars=1000`. Overlap (~150 chars) is applied only within a section — never across section boundaries. Each child `DocumentChunk` carries:
- `content` — small text for embedding/indexing
- `section_content` — full parent section text (pre-stored, shared across siblings)
- `section_header` — H3/H2 header text for citations

**Flat-doc fallback**

If no `##` or `###` headers are found, the entire document is treated as one section. `section_content` = full document, `section_header` = document title. Sub-splitting proceeds identically.

### `upsert_markdown_document()` changes

Two changes in this function:

1. Call `chunk_markdown_structured()` instead of `chunk_markdown()` at line 91.

2. Update `search_text` construction (currently line 166) to include `section_header`:

```python
# Before
search_text = f"{chunk.title or ''} {chunk.content}".strip()

# After
search_text = " ".join(filter(None, [chunk.section_header, chunk.title, chunk.content])).strip()
```

3. Write the two new fields to each `RunbookChunk` row:

```python
RunbookChunk(
    ...
    section_header=chunk.section_header,
    section_content=chunk.section_content,
)
```

---

## Section 2: Schema

Two new nullable columns on `RunbookChunk`:

```sql
section_header  VARCHAR(500)  NULL
section_content TEXT          NULL
```

Nullable so rows ingested before this change (on a live instance without a drop-and-recreate) continue to work — retrieval falls back to `chunk.content` when `section_content` is `NULL`.

`section_header` is included in `search_tsv` at ingest time so incident IDs (e.g. `INC-2024-0156`) are BM25-searchable across all child chunks of that section.

No new tables. No foreign keys. No joins at retrieval time.

**Migration note:** SQLAlchemy `create_all` does not add columns to existing tables. For deployed instances, run `python init_db.py --drop --yes` to recreate the schema (data loss — re-ingest all documents afterward). New deployments are unaffected.

---

## Section 3: Retrieval

### `find_similar_runbook_chunks()` in `incident_similarity.py`

The query itself is unchanged — hybrid vector + BM25 over `RunbookChunk`, same scoring logic. Three additions:

**Pre-query limit inflation**

To ensure enough raw candidates for deduplication, query the DB with `limit * 3` before deduplicating, then trim to `limit` afterward.

**Deduplication by section**

After scoring, group by `(source_document, section_header)`. For legacy chunks where `section_header` is `NULL`, group by `source_document` alone (treat the document as one section). Keep the highest hybrid score entry per group. The effective result set is top-`limit` *unique sections*, not top-`limit` sub-chunks.

**Context key in result dict**

```python
{
    "chunk": chunk,
    "score": score,
    "context": chunk.section_content or chunk.content,  # what callers inject into LLM prompts
}
```

Callers that want to inject runbook content into LLM prompts use `result["context"]`. This key is new — no existing caller reads `chunk.content` for prompt construction today (see note below).

**`_rerank_boost` in Jaccard fallback path**

The Jaccard fallback calls `_rerank_boost(query_text, chunk.title, chunk.content)`. Update the `content` argument to also check `section_header` for phrase matching:

```python
_rerank_boost(query_text, chunk.section_header or chunk.title, chunk.content)
```

### Note on existing callers

Neither `incident_summaries.py` nor `chat_orchestrator.py` currently injects `chunk.content` into any LLM prompt. Both files use runbook chunks for citation metadata only (`chunk.title`, `chunk.source_document`, `chunk.chunk_index`, `chunk.source_uri`). The `context` key in the result dict is the interface for future prompt-injection work — updating these callers to pass `result["context"]` to Claude is out of scope for this spec.

**Citations**

Callers building citations can now use `chunk.section_header` for specificity:
```
Auth & Sessions Runbook › INC-2024-0156 — Redis Session Store Memory Exhaustion
```
rather than the document title alone. The citation dict gains a `section_header` field alongside the existing `title`, `source_document`, `chunk_index`, `source_uri`.

---

## Section 4: Error Handling & Fallbacks

| Case | Behaviour |
|---|---|
| No `##`/`###` headers in document | Flat-doc fallback: `section_content` = full doc, `section_header` = doc title |
| Single paragraph exceeds `max_chars` | Becomes its own chunk without further splitting; `section_content` still holds the full section |
| `section_content` is `NULL` (legacy chunk) | `result["context"]` falls back to `chunk.content` transparently |
| `section_header` is `NULL` (legacy chunk) | Deduplication groups by `source_document` alone |
| Multiple sub-chunks from same section in top-k | Deduplicated — highest-scoring chunk's `section_content` sent once; tiebreaker is hybrid score |
| Very large `section_content` (edge case) | Passed as-is; ingest logs a warning if `section_content` exceeds 6,000 chars. No silent truncation. |
| `limit` parameter | Applied after deduplication. DB queried with `limit * 3` candidates to ensure enough raw results. |

---

## Section 5: Testing

### New: `tests/backend/unit/test_chunk_markdown_structured.py`

- H3-boundary splitting produces correct `section_header` / `section_content` on each chunk
- All child chunks within a section share identical `section_content`
- Overlap does not cross section boundaries
- Flat doc (no headers) falls back: `section_content` = full doc text, `section_header` = title
- Single paragraph exceeding `max_chars` becomes its own chunk; `section_content` intact
- H2-only doc (no H3) splits on H2 boundaries

### Updated: `tests/backend/unit/test_ingestion.py`

- `upsert_markdown_document()` writes `section_header` and `section_content` to DB correctly
- `search_tsv` includes `section_header` text
- Re-ingesting unchanged document skips (version hash unchanged)
- Re-ingesting changed document replaces all chunks including new columns

### Updated: retrieval tests

Cover both the pgvector path and the Jaccard fallback path:

- `find_similar_runbook_chunks()` returns `context` key using `section_content` when present
- Falls back to `chunk.content` when `section_content` is `NULL`
- Deduplication: multiple chunks from same section collapse to one result (highest hybrid score wins)
- `limit` is respected after deduplication
- Legacy chunks (`section_header=NULL`) deduplicate by `source_document`
- Jaccard fallback path: same `context` key and deduplication behaviour

---

## Files Changed

| File | Change |
|---|---|
| `backend/app/services/ingestion.py` | Add `section_header`/`section_content` to `DocumentChunk`; replace `chunk_markdown()` with `chunk_markdown_structured()`; update `upsert_markdown_document()` to write new fields and updated `search_text` |
| `backend/app/models/database.py` | Add `section_header VARCHAR(500)`, `section_content TEXT` columns to `RunbookChunk` |
| `backend/app/services/incident_similarity.py` | Add limit inflation, deduplication, `context` key to result dict; update `_rerank_boost` call in Jaccard fallback |
| `tests/backend/unit/test_chunk_markdown_structured.py` | New test file |
| `tests/backend/unit/test_ingestion.py` | Add column assertions, `search_tsv` assertion |
| `tests/backend/unit/test_incident_similarity.py` | Add deduplication, `context` key, and Jaccard fallback assertions |

### Explicitly out of scope

- `incident_summaries.py` — no change; citation metadata update (`section_header` field) is additive and backward-compatible
- `chat_orchestrator.py` — no change
- Neural embeddings — separate initiative
- Notion-specific structure — connector converts to markdown before ingestion; this design handles the resulting markdown
- Automatic `section_content` truncation — not implemented; log warning instead
