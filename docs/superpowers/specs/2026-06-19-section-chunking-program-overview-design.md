# Section chunking with contextual headers for program-overview pages

**Date:** 2026-06-19
**Status:** Approved design
**Area:** `ingestion/knowledge` (chunking), `ingestion/parsers` (label extraction)

## Problem

HUST program-overview pages (68 URLs under
`/training-cate/nganh-dao-tao-dai-hoc/`) are currently ingested with the
`whole_page` chunk strategy: one chunk = one page (~2.3k–8k chars). Each page
mixes several distinct sub-topics — *Tổng quan*, *Chương trình đào tạo*, *Cơ hội
việc làm*, *Đơn vị quản lý*.

When a user asks a sub-topic question that names a program — e.g. *"cơ hội việc
làm ngành Kỹ thuật Ô tô"* — vector search ranks the 68 whole-page embeddings.
The career-opportunity signal is a small fraction of each page embedding, so the
query matches **the wrong programs**: retrieval returns unrelated content.

Confirmed query pattern: questions **name a specific program**. Retrieval must
return the right *section* of the right *program*.

## Root cause

`whole_page` granularity dilutes any single sub-topic inside a page-level
embedding, and retrieval has no program identity signal beyond raw page-level
cosine similarity. Both failures stem from the chunk being too coarse.

## Approach (chosen: A)

Replace `whole_page` with a new `by_section` strategy for program-overview
pages, and embed a **contextual header** into every chunk so both the program
identity and the section topic live in the vector.

### 1. `by_section` chunk strategy (`ingestion/knowledge/chunker.py`)

- The HTML parser already renders section headings as `## <title>` markdown
  (see `_to_markdown`). Split the page text on lines beginning with `## `.
- Each section becomes one chunk:

  ```
  {program_label} — {section_title}

  {section_body}
  ```

  Example chunk text:

  ```
  Kỹ thuật Ô tô — Cơ hội việc làm

  Kỹ sư thiết kế, vận hành, bảo trì tại các nhà máy ô tô ...
  ```

- Drop any preamble before the first `## ` heading (breadcrumb bullets =
  navigation noise).
- A section longer than `CHUNK_SIZE` is sub-split via the existing
  `split_into_chunks`; the `{program_label} — {section_title}` header is
  re-prepended to **every** sub-chunk so context is never lost.
- Empty/whitespace sections are skipped.

`chunk_text(text, strategy, ...)` gains a `context_label` parameter (the program
label). `by_section` requires it; other strategies ignore it. Unknown strategy
still falls back to `size`.

### 2. Program label extraction (`ingestion/parsers/html_parser.py`)

`parse_html` resolves a program/page label with this fallback chain:

1. `li.breadcrumb-item.active` text (verified clean: `"Kỹ thuật Ô tô"`)
2. `<title>` text
3. URL slug, de-slugified

Exposed on `ParsedContent` as a new optional field `content_label` (default
`None`), so non-program pages are unaffected.

### 3. Metadata

Every section chunk sets the `knowledge_chunks.program` column to the program
label. The retrieval path does not filter on it yet, but populating it makes a
program metadata filter a cheap follow-up if pure-vector retrieval ever needs
reinforcement.

### 4. Retrieval — unchanged

`KnowledgeChunkRepository.vector_search(school, topic="program_overview", limit)`
is untouched. The contextual header is what makes the correct program's correct
section rank at the top under plain cosine search. `KNOWLEDGE_QA_TOP_K` stays at
5; it can be raised later without code change.

### 5. Wiring

- Seeds: the 68 `program_overview_page` entries switch `chunk_strategy`
  `whole_page` → `by_section`.
- `pipeline.run_for_source` parses the page once, obtaining both `text` and
  `content_label`, and threads `content_label` into `_chunk_embed_upsert`, which
  passes it to `chunk_text(...)` and uses it as the chunk `program` value.
- Local-PDF ingest paths keep the `size` strategy; unaffected.

## Components & boundaries

| Unit | Responsibility | Interface | Depends on |
|---|---|---|---|
| `chunk_by_section` | text + label → section chunks with headers | `(text, context_label) -> list[Chunk]` | `split_into_chunks`, settings |
| `chunk_text` dispatcher | route by strategy | `(text, strategy, *, context_label, ...)` | `chunk_by_section`, `split_into_chunks` |
| program-label extractor | page → clean program name | inside `parse_html` → `ParsedContent.content_label` | bs4 |
| pipeline wiring | parse once, pass text+label, set program | — | parser, chunker, repo |

## Error handling / edge cases

- **No `## ` headings** (page shape changes): `by_section` falls back to
  treating the whole text as one section under the label header — never empty.
- **Missing label** (all three sources fail): header omitted; chunk is the raw
  section body (degrades to plain section chunking, still better than whole
  page).
- **Re-ingest skip:** `run_for_source` skips when the fetched page
  `content_hash` is unchanged. Prior re-ingests re-ran (the site appears to vary
  per request), but if a skip occurs the re-chunk is forced by clearing the
  stored document hash before the run.

## Testing

- `chunker`: section split on `## `; header prefix present; preamble dropped;
  oversized section sub-splits with header on each part; no-heading fallback;
  empty-section skip.
- `parser`: `content_label` from breadcrumb-active, title fallback, slug
  fallback.
- Vector-quality improvement verified manually after re-ingest: a program-named
  sub-topic query returns that program's matching section as the top hit.

## Rollout

1. Implement chunker + parser + pipeline + seeds.
2. Run full `tests/ingestion/` suite.
3. Re-ingest HUST (`--school HUST`); confirm ~4 chunks/page, each headed
   `{program} — {section}`.
4. Spot-check retrieval with a known program sub-topic query.

## Out of scope

- Program metadata **filtering** in retrieval (approach B) — deferred; the
  `program` column is populated to enable it cheaply later.
- Query-side program resolution / router changes.
- Non-HUST sources and local PDFs.
