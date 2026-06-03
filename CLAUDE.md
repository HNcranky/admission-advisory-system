# CLAUDE.md

Guidance for working in this repository.

> **Never run `git push`.** You may run `git commit` when asked, but **never**
> include a `Co-Authored-By` trailer or any other Claude/AI attribution in
> commit messages.

## What this is

Conflict-aware **admission advisory assistant** for Vietnamese universities. It
crawls official sources (school admission pages, proposal PDFs), normalizes
per-program quota/method data into a canonical Postgres store, and serves a chat
UI that walks students through profile collection and program recommendations.

## Architecture

- **Advisory pipeline (LangGraph)** — `graph.py` wires nodes
  `profile → retrieve → conflict → reason → policy → explain`. Node functions
  live in `agents/`; shared graph state is `state.py::AgentState`.
- **Services** (`services/`) hold the real logic the agents call:
  - `services/inference/` — Gemini inference **gateway** (`gateway.py`), model
    `registry.py`, `providers/gemini_provider.py`, `telemetry.py`. All LLM calls
    go through `build_default_gateway()` and return an `InferenceResult`. Hard
    API failures raise `InferenceError`; malformed JSON returns
    `failure_type="STRUCTURE_FAILURE"` so the gateway can retry/fall back.
  - `services/chat/` — anonymous chat sessions, intent router, profile state,
    advisory/hybrid run dispatchers (background `ThreadPoolExecutor`), repository.
  - `services/knowledge/` — pgvector RAG (`qa_service.py`, `repository.py`).
  - `services/conflict/` — conflict detection + LLM tiebreaker.
  - `services/tracing/` — per-stage trace events for the debug panel.
- **Ingestion** (`ingestion/`) — fetchers → parsers → extractors → normalization
  → `pipeline/ingestion_pipeline.py` → `storage/db_writer.py` (canonical store).
  Per-school config drives parsers/dictionaries.
- **Web** (`web/`) — FastAPI + Jinja2 + vanilla JS chat UI. Entry: `web/app.py`.
- **DB** (`db/`) — numbered idempotent SQL migrations `001–013` in `db/migrations/`.

## Commands

```powershell
# Setup (see QUICKSTART.md for the full walkthrough)
docker compose up -d --wait db        # pgvector/pgvector:pg16 on localhost:5432
.\.venv\Scripts\python.exe -m db.setup_db
.\.venv\Scripts\python.exe -m ingestion.main --school vnu_uet

# Run the web app
.\.venv\Scripts\python.exe -m uvicorn web.app:app --reload

# Tests (testpaths is limited to tests/; integration/e2e need the Docker DB up)
.\.venv\Scripts\python.exe -m pytest -q
```

## Conventions & gotchas

- **Repositories** take an injectable `connection_factory` and use a `_cursor`
  context manager that guarantees commit/rollback + connection cleanup. Follow
  that pattern for new DB code — do not hand-roll `conn.close()`.
- **LLM call sites must degrade gracefully**: wrap `gateway.run(...)` and fall
  back to deterministic output on `InferenceError`; `logger.warning` the failure
  so outages aren't silent.
- **Secrets**: never commit `.env`, recovery codes, or scratch dumps. The Gemini
  key lives only in `.env` (gitignored).
- **SSL for crawling** is intentionally off by default (`ADVISORY_FETCH_VERIFY_SSL`,
  several official `.gov.vn` sources have broken certs) and logged per fetch.
- **Planning workflow**: specs in `docs/superpowers/specs/`, multi-slice plans in
  `docs/superpowers/plans/`. New features generally get a design spec first.
- Pydantic is **v2** throughout (`model_config = ConfigDict(...)`, not `class Config`).
- `scripts/` holds one-off probe/verify drivers (some fetch the network at
  import) — they are NOT part of the test suite.
