# Quickstart

How to run the advisory-agent locally on Windows.

## TL;DR — one-shot bootstrap

```powershell
.\setup.ps1                       # venv + deps + .env + docker db + migrations
.\.venv\Scripts\Activate.ps1      # activate venv in your shell
```

The script is idempotent — safe to re-run. Steps 1–4 below break down what it does; jump to step 3 (load `.env`) and step 6 (run the app) once it finishes.

## Prerequisites

- Python 3.12 available on `PATH` (the `py -3.12` launcher is preferred)
- Docker Desktop (or compatible runtime — `docker version` must exit 0)

## 1. Bring up the Postgres database (Docker)

The repo ships with a `docker-compose.yml` that runs `pgvector/pgvector:pg16` (Postgres 16 with the pgvector extension, required by the knowledge corpus) on `localhost:5432`. The Python app connects via `DB_CONFIG` in `ingestion/config/settings.py`, which defaults to the same host/port/credentials.

### First-time setup

```powershell
copy .env.example .env       # creates .env with safe dev defaults
docker compose up -d --wait db
python -m db.setup_db        # applies db/migrations/ and seeds the source registry
```

`--wait` blocks until the container reports `healthy` (≈5 s after first pull). `setup_db` is idempotent — safe to re-run after adding a migration.

### Day-to-day

```powershell
docker compose start db      # resume an existing container
docker compose stop db       # pause without losing data
docker compose down -v       # NUKE: drop the container AND the data volume
```

### Verify the connection

```powershell
python -c "from ingestion.storage.db_connection import get_connection; get_connection().close(); print('OK')"
```

Expected: prints `OK`.

### Port conflicts

If `5432` is already in use (e.g., a local `postgresql-x64-18` service is running), either stop it (`Stop-Service postgresql-x64-18`) or change `DB_PORT=5433` in `.env` — compose maps `${DB_PORT}:5432`, so the container internally stays on 5432 while the host-side port shifts.

### Design

See [`docs/superpowers/specs/2026-05-19-docker-postgres-db-design.md`](./docs/superpowers/specs/2026-05-19-docker-postgres-db-design.md) for the full spec and rationale.

## 2. Activate the virtualenv

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

cmd:

```cmd
.\.venv\Scripts\activate.bat
```

Confirm with `python -c "import sys; print(sys.prefix)"` — the path should end in `.venv`.

## 3. Load `.env` into the shell

The app reads `GEMINI_API_KEY` from `os.environ` directly (no `dotenv` loader). Export the values into the current shell before running anything that talks to Gemini.

PowerShell:

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#=\s][^=]*)=(.*)$') {
        Set-Item "Env:$($matches[1].Trim())" $matches[2].Trim()
    }
}
```

Verify: `echo $env:GEMINI_API_KEY` should print the key.

## 4. Run the tests

```powershell
pytest
```

Tests do not need a live Gemini key — they stub the provider.

Integration tests (`pytest -m integration`) require the Docker DB from step 1 to be running. Skip them with `pytest -m "not integration"` if Docker is unavailable.

## 5. Ingest data

Two pipeline families feed two different stores. Both need the Docker DB from
step 1; the knowledge flows also call Gemini (OCR + embeddings), so load `.env`
first (step 3).

| Pipeline | Store | Used by |
|---|---|---|
| Canonical (`ingestion.main`) | per-program quota/method tables | advisory recommendations |
| Knowledge (`ingestion.knowledge.*`) | `knowledge_chunks` (pgvector) | RAG Q&A |

> SSL verification is intentionally off by default for crawling
> (`ADVISORY_FETCH_VERIFY_SSL` — several official `.gov.vn` sources have broken
> certs); each fetch logs whether it verified.

### Canonical admission data (quota / method)

```powershell
python -m ingestion.main --list-schools     # list configured schools and sources
python -m ingestion.main --school vnu_uet   # run all sources for one school
python -m ingestion.main --source <id>      # run one registered source
python -m ingestion.main --url <url>        # process a single URL
python -m ingestion.main --all              # run every active school
```

### Knowledge corpus (pgvector RAG)

Four ways to feed it. All are idempotent — unchanged URLs `SKIP` on content
hash — and one bad URL never aborts the batch.

**a) Curated per-school seeds** — edit
`ingestion/knowledge/registry/seeds/knowledge_sources.json`, then:

```powershell
python -m ingestion.knowledge.pipeline --school HUST    # or --all
```

**b) Crawl → review manifest → ingest** — discover new PDFs on school sites:

```powershell
python -m ingestion.knowledge.crawl --school HUST       # or --all
# review data/knowledge/manifest.json: set "status" to keep / skip per entry
python -m ingestion.knowledge.ingest_manifest
```

Useful crawl flags: `--no-sitemap`, `--delay 1.0`, `--manifest <path>`.
A kept URL flips to `done` on success and stays `keep` on failure, so
re-running `ingest_manifest` retries only the failures.

**c) Local PDFs** — files already on disk:

```powershell
python -m ingestion.knowledge.pipeline --local-dir data/knowledge
```

Expects `<dir>/pdf_text/` (text-layer PDFs) and `<dir>/pdf_scanned/`
(scanned PDFs, sent through OCR).

**d) National regulations (MOET)** — curated official PDFs in
`ingestion/knowledge/seeds/national_sources.json`, ingested under the national
scope (`school="MOET"`, `document_type="national_regulation"`) so they apply to
every school's answers:

```powershell
python -m ingestion.knowledge.ingest_national           # or --sources <path>
```

### Verify the corpus

```powershell
python -m ingestion.knowledge.verify_corpus
```

Prints chunk counts per school/topic and flags schools with zero chunks or
chunks left with NULL embeddings.

## 6. Run the chat web app

```powershell
uvicorn web.app:build_app --factory --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/> in a browser. The first visit creates an anonymous session; the session token is persisted in `localStorage` so refreshing rejoins the same conversation.

### Agent tracing

Per-stage tracing now goes to Langfuse spans (`agent_tracer.traced` →
`stage_span`); the in-app trace viewer panel was retired (spec 2026-06-18).
See the Langfuse stack helper for self-hosted setup.

## 7. Demo flow

1. Send a freeform message describing a student's situation.
2. The assistant will ask follow-up questions until the profile is complete.
3. Once complete, the UI enters an "analyzing" state and polls the session snapshot until the advisory run finishes.
4. The final recommendation appears as an assistant result turn.

Stale local session tokens (e.g. after the database is wiped) are detected on startup and cleared automatically — refresh the page to recover.

### Conflict-aware advisory demo

For a stable local demo that does not require Postgres conflict rows:

```powershell
$env:ADVISORY_MOCK_CONFLICTS="1"
pytest tests/e2e/test_advisory_flow.py -k mock -v
```

The mock mode returns in-memory `CandidateProgram` rows with conflicting quota values. It is only for local development, automated tests, and fallback demos. Do not use it as evidence that the real-data dataset is complete.

For phase completion against real ingested data:

```powershell
pytest -m requires_real_dataset -v
```

This requires a reachable Postgres database and `tests/e2e/fixtures/real_dataset_dump.sql` exported from accepted HUST/VNU-UET ingestion. The real-data test is the thesis/demo-prep gate; mock mode does not replace it.

## 8. UI features

- **Theme toggle** — click `🌙` in the header to switch dark / light; preference
  persists per browser via `localStorage`. The page also honours
  `prefers-color-scheme` on first visit, and the server-side default can be
  overridden with `ADVISORY_THEME_DEFAULT=light|dark`.
- **Column collapse** — chevron handles (`◀` / `▶`) at the inner edge of each
  side panel collapse the column to a 32px gutter; click again to expand.
  Collapse state persists per browser.
- **Mobile drawer** — under 900px the side panels become overlays. Tap the
  hamburger icons in the header to open; press `Escape` or tap the backdrop
  to close.
- **Help popover** — the `?` icon opens a popover with the app version
  (read from `pyproject.toml`) and a `Bắt đầu lại` link that resets the session.
- **Markdown** — assistant final recommendations are rendered as markdown
  (bold school names, bullet lists). Loaded via `marked.js` from CDN with SRI.

### Manual smoke checklist

After any UI change run this checklist locally:

```text
1. Light → click 🌙 → dark applied immediately, reload → still dark.
2. Toggle left/right column collapse → reload → state persisted.
3. Send "Em muốn học CNTT" → user bubble right, AI follow-up bubble left.
4. Complete profile, trigger run → trace cards flip pending → running
   (spinner) → completed (duration), Vietnamese labels visible.
5. Visit /?debug=1 → trace cards become clickable, expand to show output_json.
6. Final recommendation: bold school names + bullet list render correctly
   (markdown).
7. Resize browser < 900px → side panels become drawers, header gains
   drawer-open icons.
8. Disconnect network mid-run → toast appears, polling auto-retries with backoff.
```

## Observability (Langfuse, optional)

Self-hosted, off by default. To enable:

1. Generate secrets (Git Bash / WSL):
   ```bash
   cp .env.langfuse.example .env.langfuse
   for k in LANGFUSE_SALT LANGFUSE_ENCRYPTION_KEY NEXTAUTH_SECRET CLICKHOUSE_PASSWORD MINIO_ROOT_PASSWORD POSTGRES_PASSWORD; do
     echo "$k=$(openssl rand -hex 32)"
   done
   ```
   Paste the values into `.env.langfuse`. (`LANGFUSE_ENCRYPTION_KEY` must be 64 hex chars — `openssl rand -hex 32` satisfies this.)

2. Start the stack:
   ```bash
   docker compose -f docker-compose.langfuse.yml --env-file .env.langfuse up -d
   ```

3. Open http://localhost:3000, create an account + project, copy the project's
   public/secret keys.

4. In the app `.env`, set:
   ```
   ADVISORY_LANGFUSE_ENABLED=true
   LANGFUSE_HOST=http://localhost:3000
   LANGFUSE_PUBLIC_KEY=pk-...
   LANGFUSE_SECRET_KEY=sk-...
   ```

5. Run an advisory conversation; each run appears as a trace under the project,
   grouped by session.

## Troubleshooting

- **"GEMINI_API_KEY is not configured"** — step 3 was skipped or run in a different shell than step 6. Re-run the export block in the same PowerShell window before starting uvicorn.
- **Port 8000 in use** — pass a different `--port` to uvicorn.
- **Chat page loads but shows a startup error** — open the browser devtools network tab; a `404` on `/api/sessions` means the server did not start the chat router. Restart uvicorn.
