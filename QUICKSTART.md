# Quickstart

How to run the advisory-agent locally on Windows.

## TL;DR — one-shot bootstrap

```powershell
.\setup.ps1                       # venv + deps + .env + docker db + migrations
.\.venv\Scripts\Activate.ps1      # activate venv in your shell
```

The script is idempotent — safe to re-run. Steps 1–4 below break down what it does; jump to step 3 (load `.env`) and step 5 (run the app) once it finishes.

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

## 5. Run the chat web app

```powershell
uvicorn web.app:build_app --factory --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/> in a browser. The first visit creates an anonymous session; the session token is persisted in `localStorage` so refreshing rejoins the same conversation.

### Optional: enable the trace viewer (dev-only)

Set the env flag before starting uvicorn:

```powershell
$env:ADVISORY_DEBUG_UI="1"
uvicorn web.app:build_app --factory --reload --port 8000
```

Then open `http://127.0.0.1:8000/?debug=1`. The right-hand "Phân tích của AI" panel
shows one card per agent stage with a Vietnamese label and an inline SVG icon
(`Phân tích hồ sơ`, `Tra cứu chương trình`, `Đối chiếu nguồn dữ liệu`, ...).
In debug mode each card becomes clickable and expands to pretty-printed
`output_json` for that stage. Without the env flag or query param the panel
remains visible during a run but cards are non-interactive.

## 6. Demo flow

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

## 7. UI features

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

## Troubleshooting

- **"GEMINI_API_KEY is not configured"** — step 2 was skipped or run in a different shell than step 4. Re-run the export block in the same PowerShell window before starting uvicorn.
- **Port 8000 in use** — pass a different `--port` to uvicorn.
- **Chat page loads but shows a startup error** — open the browser devtools network tab; a `404` on `/api/sessions` means the server did not start the chat router. Restart uvicorn.
