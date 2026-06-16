# FACTS.md — measured statistics for the thesis

Single source of truth for every number cited in `latex/Chapter/*.tex`.
Re-measure before the submission pass if the codebase changes.
All measurements taken **2026-06-16** on branch `refactor/codebase` unless noted.

## Codebase size

Command: `git ls-files '*.py' | xargs wc -l` (tracked files only)

| Metric | Value |
|---|---|
| Python LOC (total, incl. tests) | 31,076 |
| Python files (tracked) | 376 |
| `tests/` LOC | 15,664 |
| Production LOC (total − tests) | 15,412 |
| `ingestion/` LOC | 6,695 |
| `services/` LOC | 6,089 |
| `db/` LOC | 329 |
| `agents/` LOC | 156 |
| `web/` (Python only) LOC | 173 |
| `scripts/` LOC | 1,302 |
| root (`graph.py`, `state.py`, `main.py`) | 101 |
| Git commits on branch | 266 (as of 2026-06-16) |

## Database migrations

Command: `Get-ChildItem db\migrations` — **19 migrations**, `001_source_registry.sql`
… `018_advisory_run_queue.sql`. Numbering runs `001`–`018` but two files share the
`014_` prefix (`014_chunk_content_hash.sql`, `014_drop_discovered_resources.sql`), so
the file count (19) is one higher than the top number (018).
(OUTLINE.md / root CLAUDE.md previously said 001–013, and a prior FACTS pass said 16 —
both stale; use 19 files.)

Tables: source_registry, discovered_resources, raw_documents, extracted_facts,
canonical_admission_records, advisory_runs, chat_sessions/chat_messages/chat_advisory_runs,
advisory_trace_events, flow_state (012), knowledge_documents/knowledge_chunks (013),
program_catalog_embeddings (015), cutoff_records (016),
knowledge_chunk_doc_index (017), advisory_run_queue (018). Migration 018 backs the
**run-queue worker** (`services/chat/run_queue_worker.py`): advisory/hybrid runs are
dispatched through a persisted run queue drained by a background worker, not only the
in-process `ThreadPoolExecutor` the earlier draft described.

## Canonical store contents (dev DB `admission`, 2026-06-08)

Command: `docker exec advisory-db psql -U postgres -d admission -c "SELECT school_id, COUNT(*) ..."`

Re-measured **2026-06-17** with the Docker dev DB up (`advisory-db`, healthy):
every count below is unchanged from the 2026-06-08 baseline and is now confirmed.
(Note: `knowledge_documents` groups by column `school`, not `school_id`.)

| Table | Count |
|---|---|
| canonical_admission_records — hust | 136 |
| canonical_admission_records — vnu_uet | 20 |
| cutoff_records — hust | 699 |
| cutoff_records — vnu_uet | 16 |
| cutoff_records — **total** | 715 |
| program_catalog_embeddings | 81 |
| knowledge_documents (total) | 18 |
| — HUST | 5 |
| — MOET | 5 |
| — NEU | 5 |
| — VNU-UET | 3 |
| knowledge_chunks | 406 |
| source_registry rows | 8 |
| raw_documents / extracted_facts | 0 / 0 (working tables, cleared after promotion) |

Schools registered in ingestion CLI (`python -m ingestion.main`): **2** — `hust`
(2 active / 4 total sources), `vnu_uet` (2 active / 2 total). NEU and MOET data
entered via the knowledge-corpus path, not the canonical ingestion registry.

## Test suite

Command: `python -m pytest --collect-only -q` → **1011 tests collected** at
committed HEAD (2026-06-17). Test files: 167. Breakdown by directory: services 81,
ingestion 52, web 8, integration 6, agents 7, e2e 4 (+ fixtures, conftest).
Isolation: `tests/conftest.py::_isolate_test_db` redirects the whole suite to
an auto-created `admission_test` database; dev data untouched.
(The working tree carries an uncommitted `services/db/pool.py` refactor that adds
one test to `tests/services/db/test_pool.py`, so a dirty checkout collects 1012;
the thesis cites the committed-HEAD figure of 1011.)

Full-suite result re-run **2026-06-17** with the Docker DB up, against committed
HEAD (`git stash` of the uncommitted pool.py work), `python -m pytest -q`,
≈22 s (two clean runs: 21.79 s, 24.02 s):
**1009 passed, 1 skipped, 1 error** (of 1011 collected). The old NEU-seed failure
no longer occurs (`test_default_seed_loads_three_schools_each_with_sources` now passes).
- The 1 error is `tests/web/test_trace_endpoint_integration.py::test_trace_endpoint_returns_mixed_states_after_two_stages_complete`.
  It **passes in isolation** (verified) and errors only under full-suite execution —
  a test-ordering / shared connection-pool-state interaction, not a runtime defect.
  The uncommitted `services/db/pool.py` refactor resolves it: with that work applied
  the dirty tree runs **1011 passed, 1 skipped, 0 errors** (1012 collected).
- The 1 skip is `tests/e2e/test_real_conflict_resolution.py` — requires
  `DATABASE_URL` + a real dataset dump fixture not in the repo.

## Edge-case compliance (evaluation of 2026-06-06, branch feat/edge-case-complete)

Against the 25 cases in `docs/edge-case.md`:
**17 pass / 4 partial / 4 fail** (baseline 2026-06-04: 8 / 3 / 14).

- Pass (17): EC-01, 03, 04, 05, 06, 09, 10, 12, 13, 14, 15, 16, 17, 18, 21, 22, 24.
- Partial (4): EC-02 (no e2e re-ask test), EC-19 (tuition raw JSONB only, no
  tuition_fit in reasoning), EC-23 (no per-program band-shift causality),
  EC-25 (data_uncertain_fields covers quota only).
- Fail (4): EC-07 (no `__remove__` op for majors), EC-08 (location_preference
  flat string, unused in retrieval), EC-11 (no unresolved_major_mentions),
  EC-20 (tuition_budget flat string, no soft preference).
- Single remaining root cause: flat profile model for location/tuition +
  reasoning ignores both fields → future-work cluster "structured preferences"
  (EC-07/08/11/19/20/25), cited in §6.2.

## Contribution commits (verified `git log` 2026-06-08)

- `c2ef582` — feat: implement deterministic keyword fallback for intent classification (§5.2)
- `b41dd9f` — feat: implement degenerate OCR detection and retry mechanism to handle repetition loops (§5.3)
- `95814a1` — transparent no-match explanation (EC-24) — referenced by edge-case matrix

## Environment / library versions (`requirements.txt`, `python --version`)

| Tool | Version |
|---|---|
| Python | 3.12.0 |
| langgraph | 1.1.10 |
| langchain | 1.2.17 |
| google-genai | 1.75.0 |
| pydantic | 2.13.4 |
| psycopg2-binary | 2.9.12 |
| fastapi | 0.136.1 |
| uvicorn | 0.46.0 |
| jinja2 | 3.1.6 |
| httpx | 0.28.1 |
| pytest | 9.0.3 |
| requests | 2.33.1 |
| beautifulsoup4 | 4.14.3 |
| pdfminer.six | 20251230 |
| pdfplumber | 0.11.9 |
| pymupdf | 1.27.2.3 |
| thefuzz | 0.22.1 |
| tenacity | 9.1.4 |
| Postgres image | pgvector/pgvector:pg16 |

## Advisory pipeline shape (from `graph.py`, `agents/`)

6 pipeline stages: profile → retrieve → conflict → reason → policy → explain.
6 graph-node modules in `agents/`: profile, retrieval, conflict, reasoning,
policy, explanation. Shared domain models live in `domain/models.py`.
`services/` packages: chat, conflict, cutoff, inference, knowledge, profile,
tracing (+ legacy root-level service modules).
