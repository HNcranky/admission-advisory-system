# Quickstart

How to run the advisory-agent locally on **Linux** and **Windows**.

The repo ships a one-shot bootstrap script per platform (`setup.sh` / `setup.ps1`).
Both are idempotent — safe to re-run. Use the **First run** section once to set
the machine up; use **Later run** for every day-to-day start afterwards.

> **Shell convention used below.** Where a command differs per platform, both are
> shown (🐧 Linux / 🪟 Windows). Commands that are identical are shown once.
> On Linux, `python` means the venv interpreter — either activate the venv
> (`source .venv/bin/activate`) or call `.venv/bin/python` directly. On Windows
> after `.\.venv\Scripts\Activate.ps1`, plain `python` is the venv interpreter.

## Prerequisites

- **Python 3.12** on `PATH`.
  - 🐧 `python3.12` (stock Ubuntu may lack `python3.12-venv`/`pip` — the script
    bootstraps pip via `get-pip.py`, no sudo needed; or
    `sudo apt-get install -y python3.12-venv python3-pip`).
  - 🪟 the `py -3.12` launcher is preferred.
- **Docker** (Desktop on Windows, Engine on Linux) — `docker version` must exit 0.
  Runs `pgvector/pgvector:pg16` (Postgres 16 + pgvector, required by the
  knowledge corpus) on `localhost:5432`.

---

## First run (one-time setup)

### 1. Bootstrap

🐧 **Linux**

```bash
./setup.sh
```

🪟 **Windows (PowerShell)**

```powershell
.\setup.ps1
```

The script is idempotent and does all of:

1. create `.venv` (Linux: bootstraps pip if the venv has none),
2. `pip install -r requirements.txt`,
3. copy `.env.example` → `.env` (skipped if `.env` already exists),
4. `docker compose up -d --wait db` — `--wait` blocks until the container is
   `healthy` (≈5 s after first image pull),
5. `python -m db.setup_db` — apply `db/migrations/` and seed the source registry.

### 2. Set your Gemini key

Edit `.env` and set `GEMINI_API_KEY` (or `GEMINI_API_KEYS=key1,key2,…` for
rotation). The DB defaults in `.env.example` already match `docker-compose.yml`
(`admission` / `postgres` / `postgres` @ `localhost:5432`) — leave them unless
you hit a port conflict (see Troubleshooting).

> **`.env` loads itself.** `ingestion/config/settings.py` reads `.env` into
> `os.environ` on import — you do **not** need to export it into your shell.
> 🐧 In particular, do **not** `source .env` in bash: `GEMINI_API_KEYS` is a
> comma-separated list, so bash parses the values as a command → `exit 127`.

### 3. Verify

```bash
# DB connectivity (prints OK)
python -c "from ingestion.storage.db_connection import get_connection; get_connection().close(); print('OK')"
```

🐧 Linux uses `.venv/bin/python -c "..."` if the venv isn't activated.

---

## Later run (day-to-day)

Once setup has been done, a normal start is just two things: bring the DB up, run
the app.

### 1. Start the database container

```bash
docker compose start db      # resume the existing container (fast)
```

First start after a reboot, or if the container was removed, use
`docker compose up -d --wait db` instead.

Other lifecycle commands:

```bash
docker compose stop db       # pause without losing data
docker compose down -v       # NUKE: drop the container AND the data volume
```

### 2. Activate the venv (optional but convenient)

🐧 **Linux**

```bash
source .venv/bin/activate
```

🪟 **Windows (PowerShell)**

```powershell
.\.venv\Scripts\Activate.ps1   # or activate.bat under cmd
```

Confirm: `python -c "import sys; print(sys.prefix)"` ends in `.venv`.

### 3. Run the chat web app

```bash
uvicorn web.app:build_app --factory --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>. The first visit creates an anonymous session; the
token persists in `localStorage` so refreshing rejoins the same conversation.
Stale tokens (e.g. after the DB is wiped) are detected on startup and cleared —
just refresh.

---

## Run the tests

```bash
pytest                       # full suite
pytest -m "not integration"  # unit only — no Docker DB, no Gemini key needed
pytest -m integration        # needs the Docker DB from setup running
```

Tests stub the Gemini provider, so a live key is not required. The suite runs
against an auto-created `admission_test` database and never touches dev data in
`admission` (`tests/conftest.py::_isolate_test_db`).

---

## Ingest data

Two pipeline families feed two different stores. Both need the Docker DB; the
knowledge flows also call Gemini (OCR + embeddings), so set your key in `.env`
first.

| Pipeline | Store | Used by |
|---|---|---|
| Canonical (`ingestion.main`) | per-program quota/method tables | advisory recommendations |
| Knowledge (`ingestion.knowledge.*`) | `knowledge_chunks` (pgvector) | RAG Q&A |

> SSL verification is intentionally off by default for crawling
> (`ADVISORY_FETCH_VERIFY_SSL` — several official `.gov.vn` sources have broken
> certs); each fetch logs whether it verified.

### Canonical admission data (quota / method)

```bash
python -m ingestion.main --list-schools     # list configured schools and sources
python -m ingestion.main --school vnu_uet   # run all sources for one school
python -m ingestion.main --source <id>      # run one registered source
python -m ingestion.main --url <url>        # process a single URL
python -m ingestion.main --all              # run every active school
```

### Knowledge corpus (pgvector RAG)

Four ways to feed it. All idempotent — unchanged URLs `SKIP` on content hash —
and one bad URL never aborts the batch.

**a) Curated per-school seeds** — edit
`ingestion/knowledge/registry/seeds/knowledge_sources.json`, then:

```bash
python -m ingestion.knowledge.pipeline --school HUST    # or --all
```

**b) Crawl → review manifest → ingest** — discover new PDFs on school sites:

```bash
python -m ingestion.knowledge.crawl --school HUST       # or --all
# review data/knowledge/manifest.json: set "status" to keep / skip per entry
python -m ingestion.knowledge.ingest_manifest
```

Useful crawl flags: `--no-sitemap`, `--delay 1.0`, `--manifest <path>`.
A kept URL flips to `done` on success and stays `keep` on failure, so re-running
`ingest_manifest` retries only the failures.

**c) Local PDFs** — files already on disk:

```bash
python -m ingestion.knowledge.pipeline --local-dir data/knowledge
```

Expects `<dir>/pdf_text/` (text-layer PDFs) and `<dir>/pdf_scanned/` (scanned
PDFs, sent through OCR).

**d) National regulations (MOET)** — curated official PDFs in
`ingestion/knowledge/seeds/national_sources.json`, ingested under the national
scope (`school="MOET"`, `document_type="national_regulation"`) so they apply to
every school's answers:

```bash
python -m ingestion.knowledge.ingest_national           # or --sources <path>
```

### Verify the corpus

```bash
python -m ingestion.knowledge.verify_corpus
```

Prints chunk counts per school/topic and flags schools with zero chunks or
chunks left with NULL embeddings.

---

## Demo flow

1. Send a freeform message describing a student's situation.
2. The assistant asks follow-up questions until the profile is complete.
3. The UI enters an "analyzing" state and polls the session snapshot until the
   advisory run finishes.
4. The final recommendation appears as an assistant result turn.

### Conflict-aware advisory demo

For a stable local demo that does not require Postgres conflict rows:

🐧 **Linux**

```bash
ADVISORY_MOCK_CONFLICTS=1 pytest tests/e2e/test_advisory_flow.py -k mock -v
```

🪟 **Windows (PowerShell)**

```powershell
$env:ADVISORY_MOCK_CONFLICTS="1"
pytest tests/e2e/test_advisory_flow.py -k mock -v
```

Mock mode returns in-memory `CandidateProgram` rows with conflicting quota
values. For local dev / tests / fallback demos only — not evidence that the
real-data dataset is complete.

For phase completion against real ingested data:

```bash
pytest -m requires_real_dataset -v
```

Requires a reachable Postgres database and
`tests/e2e/fixtures/real_dataset_dump.sql` exported from accepted HUST/VNU-UET
ingestion. This is the thesis/demo-prep gate; mock mode does not replace it.

---

## UI features

- **Theme toggle** — click `🌙` to switch dark / light; persists per browser via
  `localStorage`. Honours `prefers-color-scheme` on first visit; server default
  overridable with `ADVISORY_THEME_DEFAULT=light|dark`.
- **Column collapse** — chevron handles (`◀` / `▶`) collapse each side panel to a
  32px gutter; click again to expand. State persists per browser.
- **Mobile drawer** — under 900px side panels become overlays. Tap the hamburger
  icons to open; `Escape` or tap backdrop to close.
- **Help popover** — the `?` icon shows the app version (from `pyproject.toml`)
  and a `Bắt đầu lại` link that resets the session.
- **Markdown** — assistant final recommendations render as markdown (bold school
  names, bullet lists) via `marked.js` from CDN with SRI.

### Manual smoke checklist

After any UI change run this locally:

```text
1. Light → click 🌙 → dark applied immediately, reload → still dark.
2. Toggle left/right column collapse → reload → state persisted.
3. Send "Em muốn học CNTT" → user bubble right, AI follow-up bubble left.
4. Complete profile, trigger run → trace cards flip pending → running
   (spinner) → completed (duration), Vietnamese labels visible.
5. Visit /?debug=1 → trace cards become clickable, expand to show output_json.
6. Final recommendation: bold school names + bullet list render correctly.
7. Resize browser < 900px → side panels become drawers.
8. Disconnect network mid-run → toast appears, polling auto-retries with backoff.
```

---

## Observability (Langfuse, optional)

Per-stage tracing goes to Langfuse spans (`agent_tracer.traced` → `stage_span`);
the in-app trace viewer was retired (spec 2026-06-18). Self-hosted, off by
default. To enable:

1. Generate secrets (🐧 bash / 🪟 Git Bash or WSL):
   ```bash
   cp .env.langfuse.example .env.langfuse
   for k in LANGFUSE_SALT LANGFUSE_ENCRYPTION_KEY NEXTAUTH_SECRET CLICKHOUSE_PASSWORD MINIO_ROOT_PASSWORD POSTGRES_PASSWORD; do
     echo "$k=$(openssl rand -hex 32)"
   done
   ```
   Paste the values into `.env.langfuse`. (`LANGFUSE_ENCRYPTION_KEY` must be 64
   hex chars — `openssl rand -hex 32` satisfies this.)

2. Start the stack:
   ```bash
   docker compose -f docker-compose.langfuse.yml --env-file .env.langfuse up -d
   ```

3. Open <http://localhost:3000>, create an account + project, copy the project's
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

---

## Troubleshooting

- **"GEMINI_API_KEY is not configured"** — set it in `.env` (`.env` auto-loads on
  import, so a missing/blank value here is the usual cause). 🐧 Do **not**
  `source .env` in bash — the comma-separated `GEMINI_API_KEYS` list breaks the
  shell.
- **Port 5432 already in use** — another Postgres (🪟 e.g. a local
  `postgresql-x64-18` service, 🐧 a system `postgresql` unit) holds the port.
  Stop it (🪟 `Stop-Service postgresql-x64-18`, 🐧 `sudo systemctl stop postgresql`)
  or set `DB_PORT=5433` in `.env` — compose maps `${DB_PORT}:5432`, so the
  container stays on 5432 internally while the host-side port shifts.
- **🐧 `docker compose up` errors on the container name** — a
  `pgvector/pgvector:pg16` container named `advisory-db` may already exist from a
  prior setup. If it's healthy on 5432, just reuse it: `docker compose start db`
  (or `docker start advisory-db`) and run `python -m db.setup_db` against it.
- **Port 8000 in use** — pass a different `--port` to uvicorn.
- **Chat page loads but shows a startup error** — open browser devtools network
  tab; a `404` on `/api/sessions` means the chat router didn't start. Restart
  uvicorn.
- **🐧 venv has no pip** — stock Ubuntu may omit `python3.12-venv`. `setup.sh`
  bootstraps pip via `get-pip.py` automatically; or
  `sudo apt-get install -y python3.12-venv python3-pip` and re-run.

---

## Design references

- Docker Postgres DB:
  [`docs/superpowers/specs/2026-05-19-docker-postgres-db-design.md`](./docs/superpowers/specs/2026-05-19-docker-postgres-db-design.md)
