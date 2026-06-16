# HTML selector knowledge ingestion — plan index

Spec: `docs/superpowers/specs/2026-06-15-html-selector-knowledge-ingestion-design.md`

Adds an optional per-source CSS `selector` to the existing HTML knowledge
ingestion path. Split into three small, independently-testable plans.

## Plans (run in order)

| # | Plan | Touches | Depends on |
|---|------|---------|-----------|
| 01 | `01-parser-selector.md` | `ingestion/parsers/html_parser.py` | — |
| 02 | `02-registry-field.md` | `ingestion/knowledge/registry/models.py` | — |
| 03 | `03-pipeline-wiring.md` | `ingestion/knowledge/pipeline.py` | 01 (`ContentSelectorNotFound`) + 02 (`selector` field) |

01 and 02 are independent of each other and can be done in either order. 03
consumes both, so do it last.

## Definition of done (whole feature)

- A `knowledge_sources.json` entry with `"selector": "#content"` ingests only
  that region's text.
- A wrong selector skips that one source with a `WARNING` and writes nothing;
  the rest of the batch proceeds.
- `selector` omitted → behavior byte-for-byte unchanged.
- `pytest -q` green (the selector unit tests need no DB; full suite needs the
  Docker DB per `CLAUDE.md`).
