# Design: Per-source CSS selector for HTML knowledge ingestion

**Date:** 2026-06-15
**Status:** Approved (brainstorm)

## Goal

Let a curator point the knowledge ingester at a specific region of an HTML page
by declaring a CSS selector **per source**, instead of relying solely on the
fixed auto-detect fallback chain. The motivating case: official exam pages (TSA
— HUST's Đánh giá tư duy, HSA — VNU's Đánh giá năng lực) whose useful content
lives in a known container (e.g. `#content`) while the page also carries menus,
banners and footers that pollute a whole-`<body>` extraction.

This is a **small extension of the existing registry path**, not a new
subsystem. `knowledge_sources.json` + `KnowledgeRegistry` + `run_for_source` +
`parse_html` already crawl HTML via URL and extract body text; the only gap is
the inability to target a region. We add one optional field and thread it
through the existing fetch → extract → chunk → embed → upsert pipeline. No
parallel crawler, no second JSON file.

## Non-goals

- No new `topic` / `document_type` taxonomy entries. TSA/HSA reuse existing
  values (`topic="admission_policy"`, `document_type="faq"` or `"handbook"`).
- No changes to the PDF, national (`ingest_national`), or local-dir paths.
- No `title` field. The registry has no column to persist it and retrieval never
  reads it; adding it would be a dead field (YAGNI). Human-facing labels live in
  the source URL / commit message.
- No multi-element merge. A selector targets **one** region (first match).

---

## Data model

`ingestion/knowledge/registry/models.py` — add one optional field to
`KnowledgeSource`:

```python
selector: str | None = None   # CSS selector; HTML sources only
```

- A **CSS selector string** consumed by BeautifulSoup `.select_one()`, so it
  supports `#content`, `.entry-content`, `div.body`, `article > .post`, etc.
- Defaults to `None`. Every existing seed entry (which omits the field) keeps
  validating and keeps today's behavior. No taxonomy validation on this field.

## Extraction behavior

`ingestion/parsers/html_parser.py` — `parse_html(content, url="", selector=None)`:

- `selector is None` → **unchanged**: `_find_content_area` runs its existing
  fallback chain (`article → .content → .post-content → .entry-content →
  .article-content → main → #content → [role=main] → <body>`).
- `selector` provided → resolve the content area with `soup.select_one(selector)`:
  - **Match** → extract text from that element only. The global strip of
    `script/style/noscript/iframe` still happens first (unchanged), so the
    selected region is already clean.
  - **No match** → raise `ContentSelectorNotFound(selector, url)` (new exception
    defined in `html_parser.py`). Fail loud — never silently fall back to
    `<body>` and ingest the wrong region.
- First-match semantics (`select_one`). A selector denotes a single region;
  refine the selector if a page needs a different/combined region.

## Wiring

`ingestion/knowledge/pipeline.py`:

- `run_for_source` passes `source.selector` into
  `_extract_text(fetch_result, url, selector)`, which forwards it to
  `parse_html(..., selector=selector)` on the HTML branch.
- `run_for_source` wraps the extract call: on `ContentSelectorNotFound`, log a
  `WARNING` and return `KnowledgeIngestResult(source_url=..., skipped=True)`
  **without writing to the DB**. The per-school / `--all` batch driver continues
  with the next source (existing "one bad URL never aborts the batch"
  guarantee). Re-running after fixing the selector is idempotent.
- Selector is meaningful only for HTML. If a source's URL resolves to a PDF
  (`_extract_text`'s PDF branch) **and** `selector` is set, log a `WARNING`
  ("selector ignored for PDF source") and ingest the PDF normally.

## Tests (TDD)

- `tests/ingestion/test_html_parser_selector.py` (new):
  1. selector matches → returned text is exactly the selected region's text, and
     excludes content outside it (e.g. a sibling `<nav>`/`<footer>`).
  2. selector matches nothing → `parse_html` raises `ContentSelectorNotFound`.
  3. `selector=None` → regression: output identical to the current
     `_find_content_area` path on a fixture page.
- `tests/ingestion/knowledge/test_registry.py`: a seed entry with `selector`
  loads and exposes it; entries without the field still validate (default
  `None`).
- `tests/ingestion/knowledge/test_pipeline_runners.py` (or `test_pipeline.py`):
  `run_for_source` with a selector that misses → result `skipped=True`, a logged
  warning, and **zero** chunk/document writes (assert against mocked repos).

## Acceptance

- A `knowledge_sources.json` entry with `selector` ingests only the targeted
  region's text; the chunks contain no menu/footer noise from the page.
- A wrong/stale selector skips that one source with a warning and writes nothing,
  while the rest of the batch ingests normally.
- `selector=None` (all existing seeds) is byte-for-byte unchanged in behavior.
- Full `pytest -q` green against `admission_test`.

## Usage

```json
{
  "school": "MOET",
  "source_url": "https://...",
  "document_type": "faq",
  "topic": "admission_policy",
  "fetch_strategy": "http",
  "selector": "#content"
}
```

```powershell
python -m ingestion.knowledge.pipeline --school MOET   # or --all
python -m ingestion.knowledge.verify_corpus
```

`school="MOET"` puts the page under the national scope, so
`qa_service._augment_with_national` surfaces it for every school's question
(cross-school reach, the original motivation).
