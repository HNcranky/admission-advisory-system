# Plan 01: Compose Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring up a healthy `postgres:16-alpine` container via `docker compose` and confirm the host Python app can connect using default config.

**Architecture:** Single-service `docker-compose.yml` at repo root maps Postgres to `localhost:5432`, persists to a named Docker volume `advisory_pgdata`, and exposes a `pg_isready` healthcheck. Credentials and connection params flow from `.env` (gitignored) with safe defaults baked into compose's `${VAR:-fallback}` syntax. The Python `DB_CONFIG` in `ingestion/config/settings.py` keeps the same env-var contract; only the in-code default password is rotated from `"1"` to `"postgres"` so it matches the container default.

**Tech Stack:** Docker Compose v2, `postgres:16-alpine`, `psycopg2-binary` (already in requirements).

**Prerequisite:** Docker Desktop running (`docker version` exits 0). Port 5432 free (stop `postgresql-x64-18` Windows service if running).

---

### Task 1: Rotate the in-code default password from `"1"` to `"postgres"`

This is a single-character semantic change. The new default aligns with the compose default so the system works zero-config when `.env` is absent.

**Files:**
- Modify: `ingestion/config/settings.py:40`

- [ ] **Step 1: Read the current line to confirm the target**

Run: `python -c "from ingestion.config.settings import DB_CONFIG; print(repr(DB_CONFIG['password']))"`

Expected: `'1'`. If different, somebody changed it; stop and reconcile before editing.

- [ ] **Step 2: Apply the edit**

Open `ingestion/config/settings.py`. Find the `DB_CONFIG` dict (around line 35-41). Change line 40 from:

```python
    "password": os.getenv("DB_PASSWORD", "1"),
```

to:

```python
    "password": os.getenv("DB_PASSWORD", "postgres"),
```

Leave every other line of `DB_CONFIG` untouched.

- [ ] **Step 3: Verify the new default in a clean subprocess**

Run:

```powershell
python -c "import os; [os.environ.pop(k, None) for k in list(os.environ) if k.startswith('DB_')]; from ingestion.config.settings import DB_CONFIG; print(DB_CONFIG['password'])"
```

Expected stdout: `postgres`

Why a subprocess: the parent shell may have inherited `DB_PASSWORD` from a previous `.env` load. Spawning a clean Python process guarantees the default kicks in.

- [ ] **Step 4: Confirm no other tests broke**

Run: `python -m pytest tests/ingestion/test_settings_env.py -v`

Expected: 2 passed (the existing env-loader tests are unrelated to `DB_CONFIG`, so they should still pass).

---

### Task 2: Create `.env.example` template

A committed, version-controlled template so new developers know which env vars exist and what the safe defaults are.

**Files:**
- Create: `.env.example`

- [ ] **Step 1: Create the file with the canonical template**

Write `.env.example` at repo root with exactly this content:

```
# Database (consumed by docker-compose.yml and ingestion/config/settings.py)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=admission
DB_USER=postgres
DB_PASSWORD=postgres

# LLM
GEMINI_API_KEY=
```

- [ ] **Step 2: Verify the template parses with the same env-loader the app uses**

Run:

```powershell
python -c "from pathlib import Path; from ingestion.config import settings; import os; [os.environ.pop(k, None) for k in list(os.environ) if k.startswith('DB_')]; settings._load_env_file(Path('.env.example')); print(os.environ['DB_HOST'], os.environ['DB_PORT'], os.environ['DB_NAME'], os.environ['DB_USER'], os.environ['DB_PASSWORD'])"
```

Expected stdout: `localhost 5432 admission postgres postgres`

- [ ] **Step 3: Confirm `.env` (the developer-local file) is gitignored**

Run: `git check-ignore .env`

Expected: prints `.env`, exit code 0. (Already covered by line 138 of `.gitignore`.)

If exit code is non-zero, add `.env` to `.gitignore` before continuing.

---

### Task 3: Write `docker-compose.yml`

The single source of truth for the DB container. Uses named volume so data survives `docker compose down` (data is removed only by `down -v`).

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Create the compose file**

Write `docker-compose.yml` at repo root with exactly this content:

```yaml
services:
  db:
    image: postgres:16-alpine
    container_name: advisory-db
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${DB_NAME:-admission}
      POSTGRES_USER: ${DB_USER:-postgres}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-postgres}
    ports:
      - "${DB_PORT:-5432}:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-postgres} -d ${DB_NAME:-admission}"]
      interval: 5s
      timeout: 3s
      retries: 10
      start_period: 5s

volumes:
  pgdata:
    name: advisory_pgdata
```

No `version:` key — modern Compose v2 ignores it; spec compliance.

- [ ] **Step 2: Validate compose schema and variable substitution**

Run: `docker compose config --quiet`

Expected: exits 0, no output. This validates the YAML and resolves every `${VAR:-default}` expression.

If it complains about an env var, add the missing default to the compose file — do not add it to `.env` (the file must work without `.env`).

- [ ] **Step 3: Inspect the fully resolved config**

Run: `docker compose config | grep -E "image:|container_name:|POSTGRES_|ports:|name: advisory_pgdata"`

Expected output contains (order may vary):
```
    image: postgres:16-alpine
    container_name: advisory-db
      POSTGRES_DB: admission
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    name: advisory_pgdata
```
and one mapping line for ports including `5432:5432`.

---

### Task 4: Start the container and verify healthcheck passes

**Files:**
- No file changes. Side effect: creates Docker volume `advisory_pgdata` and container `advisory-db`.

- [ ] **Step 1: Confirm port 5432 is free**

Run: `netstat -ano | findstr :5432`

Expected: no output (port free). If something is listening:
- If it is your old `postgresql-x64-18` service: `Stop-Service postgresql-x64-18`.
- Otherwise stop the conflicting process before continuing.

- [ ] **Step 2: Bring up the container, wait for healthy**

Run: `docker compose up -d --wait db`

Expected: prints `Container advisory-db Started` then `Container advisory-db Healthy`. Exit code 0 within ~10 seconds.

`--wait` blocks until the healthcheck reports healthy; if the container fails to become healthy within `start_period + interval * retries` (≈55s) the command exits non-zero.

- [ ] **Step 3: Inspect health status directly**

Run: `docker inspect --format "{{.State.Health.Status}}" advisory-db`

Expected: `healthy`

- [ ] **Step 4: Verify the named volume exists**

Run: `docker volume inspect advisory_pgdata --format "{{.Name}}"`

Expected: `advisory_pgdata`

---

### Task 5: Confirm host Python can connect via `DB_CONFIG`

This is the end-to-end smoke that proves the spec's drop-in promise: app code reads `DB_CONFIG`, gets `localhost:5432, postgres/postgres, db=admission`, and connects.

**Files:**
- No file changes.

- [ ] **Step 1: Open a `psycopg2` connection using the same config the app uses**

Run:

```powershell
python -c "from ingestion.storage.db_connection import get_connection; conn = get_connection(); cur = conn.cursor(); cur.execute('SELECT version()'); print(cur.fetchone()[0]); conn.close()"
```

Expected stdout begins with `PostgreSQL 16.` (any 16.x patch is fine).

If you see `connection refused` → container is not up; rerun Task 4 Step 2.
If you see `password authentication failed` → `.env` has stale `DB_PASSWORD`; either delete the `DB_PASSWORD` line from `.env` or set it to `postgres`.
If you see `database "admission" does not exist` → container was created with different `POSTGRES_DB`; run `docker compose down -v && docker compose up -d --wait db` to recreate the volume.

- [ ] **Step 2: Verify the connection respects custom env override (regression guard)**

Run:

```powershell
$env:DB_PASSWORD = "intentionally-wrong"; python -c "from ingestion.storage.db_connection import get_connection; get_connection()" ; Remove-Item env:DB_PASSWORD
```

Expected: prints a stack trace ending in `psycopg2.OperationalError: ... password authentication failed`. This proves env vars override the in-code default (so the `"postgres"` default does not silently mask a misconfigured env). The `Remove-Item` at the end restores the shell state.

---

### Task 6: Stop / restart sanity check (volume persistence)

Proves named-volume persistence so users can trust `docker compose stop && start` without losing data.

**Files:**
- No file changes.

- [ ] **Step 1: Write a marker row inside Postgres**

Run:

```powershell
docker compose exec -T db psql -U postgres -d admission -c "CREATE TABLE _persist_check(id int); INSERT INTO _persist_check VALUES (42);"
```

Expected: `CREATE TABLE` and `INSERT 0 1` printed.

- [ ] **Step 2: Stop the container (without `-v`)**

Run: `docker compose stop db`

Expected: `Container advisory-db Stopped`.

- [ ] **Step 3: Start again**

Run: `docker compose start db`

Expected: `Container advisory-db Started`. Wait ~5s for healthcheck.

- [ ] **Step 4: Re-query the marker row**

Run:

```powershell
docker compose exec -T db psql -U postgres -d admission -c "SELECT * FROM _persist_check;"
```

Expected: a single row with `id = 42`.

- [ ] **Step 5: Clean up the marker table**

Run:

```powershell
docker compose exec -T db psql -U postgres -d admission -c "DROP TABLE _persist_check;"
```

Expected: `DROP TABLE`.

---

### Plan-01 acceptance gate

All of the following must be true before moving to Plan 02:

- [ ] `docker compose up -d --wait db` returns success and `docker inspect` reports `healthy`.
- [ ] `python -c "from ingestion.storage.db_connection import get_connection; get_connection().close()"` exits 0.
- [ ] `python -m pytest tests/ingestion/test_settings_env.py -v` still passes (2 tests).
- [ ] `git status` lists `docker-compose.yml`, `.env.example`, `ingestion/config/settings.py` as the only modified/new repo files (no stray scratch files).

### Commit checklist (user runs `git commit` themselves)

Suggested staging:

```bash
git add docker-compose.yml .env.example ingestion/config/settings.py
```

Suggested message:

```
chore(db): add docker-compose for postgres dev DB

- Postgres 16-alpine container on localhost:5432 with named volume.
- .env.example template; settings.py default password aligned with compose.
- Drop-in replacement: existing DB_CONFIG continues to read from env.
```

Do NOT run the commit; leave staging in place for user inspection.
