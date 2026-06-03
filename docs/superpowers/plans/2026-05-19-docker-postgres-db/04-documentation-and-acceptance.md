# Plan 04: Documentation & Final Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Docker DB workflow discoverable by adding a `Database (Docker)` section to `QUICKSTART.md`, a high-level pointer in `README.md`, then run all 10 spec acceptance criteria as a single end-to-end manual gate.

**Architecture:** Docs only — no code changes. `QUICKSTART.md` already has a numbered setup flow (`Prerequisites → Activate venv → Load .env → Run tests → Run web`); insert the Docker DB setup as a new step after Prerequisites so it's the first thing a new dev does after cloning. `README.md` is currently a stub; expand it with a one-paragraph intro + setup link.

**Tech Stack:** Markdown.

**Prerequisites:** Plans 01–03 complete.

---

### Task 1: Expand `README.md` from a stub into a useful landing page

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the stub with a useful intro**

The current `README.md` is one line (`# advisory-agent`). Replace its full contents with the block below (the outer fence uses four backticks so the inner ```` ```bash ```` block renders correctly — when you paste into `README.md`, drop the outer four-backtick fence and keep the inner content verbatim):

````markdown
# advisory-agent

Conflict-aware admission advisory assistant for Vietnamese universities. Crawls official sources (school admission pages, proposal PDFs), normalizes per-program quota/method data into a canonical store, and serves a chat UI that walks students through profile collection and program recommendations.

## Quick links

- **Local setup:** [`QUICKSTART.md`](./QUICKSTART.md)
- **DB on Docker design:** [`docs/superpowers/specs/2026-05-19-docker-postgres-db-design.md`](./docs/superpowers/specs/2026-05-19-docker-postgres-db-design.md)
- **Implementation plans:** [`docs/superpowers/plans/`](./docs/superpowers/plans/)
- **Crawl pipeline:** `python -m ingestion.main --list-schools`

## TL;DR — get the stack running

```bash
cp .env.example .env          # adjust if your shell exposes DB_* already
docker compose up -d --wait db
python -m db.setup_db
python -m ingestion.main --school vnu_uet
```

See `QUICKSTART.md` for the full walkthrough.
````

- [ ] **Step 2: Verify the relative links resolve**

Run:

```powershell
$readme = Get-Content README.md -Raw
foreach ($p in @('QUICKSTART.md', 'docs/superpowers/specs/2026-05-19-docker-postgres-db-design.md', 'docs/superpowers/plans')) {
    if (Test-Path $p) { "OK  $p" } else { "MISS $p" }
}
```

Expected: every path prints `OK ...`. If any prints `MISS`, fix the link to point to the actual file.

- [ ] **Step 3: Confirm the README renders as valid Markdown**

Run: `python -c "import re; t=open('README.md', encoding='utf-8').read(); print('hash-headings:', len(re.findall(r'^#', t, re.M))); print('code-fences:', t.count('\`\`\`') // 2)"`

Expected: `hash-headings: 3` (one h1, two h2s) and `code-fences: 1` (one fenced block — the bash quickstart).

---

### Task 2: Add the `Database (Docker)` section to `QUICKSTART.md`

Slot it between the existing `Prerequisites` and `1. Activate the virtualenv` sections so a developer does it once on first checkout.

**Files:**
- Modify: `QUICKSTART.md`

- [ ] **Step 1: Update the Prerequisites list to include Docker**

Open `QUICKSTART.md`. The `## Prerequisites` block currently has:

```markdown
## Prerequisites

- Python 3.12 with the project virtualenv already created at `.venv/`
- `.env` at the repo root containing `GEMINI_API_KEY=...`
```

Replace those two bullet lines with:

```markdown
## Prerequisites

- Python 3.12 with the project virtualenv already created at `.venv/`
- Docker Desktop (or compatible runtime — `docker version` must exit 0)
- `.env` at the repo root (copy `.env.example` if absent)
```

- [ ] **Step 2: Insert the Docker DB section**

Insert this entire block immediately before the `## 1. Activate the virtualenv` heading. It becomes the new step 1; renumber subsequent sections.

````markdown
## 1. Bring up the Postgres database (Docker)

The repo ships with a `docker-compose.yml` that runs Postgres 16-alpine on `localhost:5432`. The Python app connects via `DB_CONFIG` in `ingestion/config/settings.py`, which defaults to the same host/port/credentials.

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

````

- [ ] **Step 3: Renumber the subsequent sections**

The original `## 1. Activate the virtualenv` becomes `## 2.`. Continue renumbering through to the last numbered section so the order stays monotonic:

- `## 1. Activate the virtualenv` → `## 2. Activate the virtualenv`
- `## 2. Load .env into the shell` → `## 3. Load .env into the shell`
- `## 3. Run the tests` → `## 4. Run the tests`
- `## 4. Run the chat web app` → `## 5. Run the chat web app`
- `## 5. Demo flow` → `## 6. Demo flow`

- [ ] **Step 4: Update the test section to mention integration tests**

Inside the renumbered `## 4. Run the tests` block, append after the existing line `Tests do not need a live Gemini key — they stub the provider.`:

```markdown

Integration tests (`pytest -m integration`) require the Docker DB from step 1 to be running. Skip them with `pytest -m "not integration"` if Docker is unavailable.
```

- [ ] **Step 5: Verify the file still renders cleanly**

Run:

```powershell
python -c "import re; t=open('QUICKSTART.md', encoding='utf-8').read(); print('h2-headings:', re.findall(r'^## ', t, re.M))"
```

Expected: a Python list containing 8 entries — `## ` prefixes for `Prerequisites`, `1. Bring up...`, `2. Activate...`, `3. Load...`, `4. Run the tests`, `5. Run the chat...`, `6. Demo flow`, `Troubleshooting`. Order must be monotonically numbered with no gaps.

---

### Task 3: Run the 10 spec acceptance criteria end-to-end

This is the final manual gate. Each step is one of the 10 acceptance criteria from §12 of the spec. Execute in order; if any fails, fix before signing off.

**Files:**
- No file changes (this is a verification task).

- [ ] **Step 1: AC1 — clean compose up**

Run:

```powershell
docker compose down -v
docker compose up -d --wait db
```

Expected: exit code 0; final line `Container advisory-db Healthy`.

- [ ] **Step 2: AC2 — healthcheck under 10 s**

Run (timed):

```powershell
docker compose down -v
$sw = [Diagnostics.Stopwatch]::StartNew()
docker compose up -d --wait db
$sw.Stop(); "$($sw.ElapsedMilliseconds) ms"
```

Expected: `<10000 ms` printed at the end. Cold image pull may exceed 10 s on the very first run; if so, repeat the timing — every subsequent cold start must be under 10 s.

- [ ] **Step 3: AC3 — setup_db applies migrations + seeds 2 sources**

Run: `python -m db.setup_db`

Expected: all 10 migration lines `✅ applied`, all 9 expected tables `✅`, `🌱 Seeded 2 sources into source_registry`, final `✅ Setup complete!`. Exit code 0.

- [ ] **Step 4: AC4 — pipeline produces 20 records**

Run: `python -m ingestion.main --school vnu_uet --output .acc-test-records.json`

Expected: log line `Pipeline complete: 20 normalized records`. The output file contains 20 entries (verify with `python -c "import json; print(len(json.load(open('.acc-test-records.json', encoding='utf-8'))))"` → `20`).

- [ ] **Step 5: AC5 — integration suite passes**

Run: `python -m pytest -m integration -v`

Expected: 4 passed (the 2 fixture sanity tests + the 2 E2E tests from Plan 03).

- [ ] **Step 6: AC6 — unit suite passes without DB**

Run: `python -m pytest -m "not integration" --ignore=tests/services/test_reasoning_inference_service.py -q 2>&1 | Select-Object -Last 3`

Expected: ends with `N passed, 2 failed`. The two known failures (`tests/agents/test_profile_agent.py::test_profile_agent_uses_injected_gateway` and `tests/services/test_profile_inference_service.py::test_build_profile_with_gateway_falls_back_when_gateway_is_unavailable`) and the collection error in `tests/services/test_reasoning_inference_service.py` (which `--ignore` skips) all live on `main` and are NOT regressions from this work. Any other failure IS a regression and must be fixed before signing off.

- [ ] **Step 7: AC7 — stop/start preserves data**

Run:

```powershell
docker compose exec -T db psql -U postgres -d admission -c "INSERT INTO canonical_admission_records (school_id, school_name_canonical, admission_year, program_id, admission_method, source_url) VALUES ('ac7', 'AC7', 2099, 'p', 'm', 'http://ac7');"
docker compose stop db
docker compose start db
Start-Sleep -Seconds 6
docker compose exec -T db psql -U postgres -d admission -c "SELECT COUNT(*) FROM canonical_admission_records WHERE school_id='ac7';"
docker compose exec -T db psql -U postgres -d admission -c "DELETE FROM canonical_admission_records WHERE school_id='ac7';"
```

Expected from the count query: `1`. The delete at the end cleans up the marker row.

- [ ] **Step 8: AC8 — down -v wipes; setup_db restores clean state**

Run:

```powershell
docker compose down -v
docker compose up -d --wait db
python -m db.setup_db
docker compose exec -T db psql -U postgres -d admission -c "SELECT COUNT(*) FROM canonical_admission_records;"
docker compose exec -T db psql -U postgres -d admission -c "SELECT COUNT(*) FROM source_registry;"
```

Expected: canonical rows `0`, source rows `2` (the 2 VNU-UET seeds).

- [ ] **Step 9: AC9 — `.env.example` is committable; `.env` is gitignored**

Run:

```powershell
Test-Path .env.example
git check-ignore .env.example; "exit=$LASTEXITCODE"
git check-ignore .env;         "exit=$LASTEXITCODE"
```

Expected:
- `Test-Path .env.example` prints `True` — the template exists.
- `git check-ignore .env.example` prints nothing with `exit=1` — the template is NOT gitignored (i.e., it WILL be committed when staged).
- `git check-ignore .env` prints `.env` with `exit=0` — the developer-local file IS gitignored.

(This verifies the invariants regardless of whether the user has already run `git commit` — plans avoid committing intentionally.)

- [ ] **Step 10: AC10 — docs reference the spec**

Run:

```powershell
Select-String -Path README.md, QUICKSTART.md -Pattern "2026-05-19-docker-postgres-db-design.md"
```

Expected: at least one match each in `README.md` and `QUICKSTART.md`.

- [ ] **Step 11: Cleanup ephemeral artifacts**

Run:

```powershell
Remove-Item .acc-test-records.json -ErrorAction SilentlyContinue
git status
```

Expected: `.acc-test-records.json` is gone. `git status` shows only the intended changes (`README.md`, `QUICKSTART.md`, and the docs/plans/spec from earlier plans if not yet committed).

---

### Plan-04 acceptance gate

All of the following must be true to declare the spec implemented:

- [ ] `README.md` is a real landing page with links to QUICKSTART, the spec, and plans.
- [ ] `QUICKSTART.md` has a `Database (Docker)` section as step 1, with subsequent sections renumbered.
- [ ] All 10 acceptance criteria from §12 of the spec produce the expected output.
- [ ] No scratch/temp files left in the working tree (`git status` shows only intended changes).

### Commit checklist (user runs `git commit` themselves)

Suggested staging:

```bash
git add README.md QUICKSTART.md
```

Suggested message:

```
docs: document Docker DB setup in README and QUICKSTART

Add a top-level README intro with project description and quick
links. Insert "Database (Docker)" as step 1 of QUICKSTART and
renumber subsequent setup steps. Reference the spec doc for the
full design.
```

Do NOT run the commit; leave staging in place for user inspection.

---

### Combined commit option (all 4 plans at once)

If the user prefers a single PR commit covering all four plans, the full staging list is:

```bash
git add \
  docker-compose.yml \
  .env.example \
  ingestion/config/settings.py \
  db/migrations/010_canonical_records_per_source.sql \
  pyproject.toml \
  tests/integration/ \
  README.md \
  QUICKSTART.md \
  docs/superpowers/specs/2026-05-19-docker-postgres-db-design.md \
  docs/superpowers/plans/2026-05-19-docker-postgres-db/
```

Suggested combined message:

```
feat(db): migrate dev Postgres from Windows service to Docker

- docker-compose.yml with postgres:16-alpine, named volume,
  pg_isready healthcheck, env-driven config.
- .env.example template; settings.py default password aligned
  with compose so the system is zero-config out of the box.
- Migration 010 patched to be idempotent (guarded ADD CONSTRAINT).
- tests/integration/ suite with skip-on-no-DB fixtures; vnu_uet
  pipeline E2E smoke + per-source unique constraint regression
  guard.
- README + QUICKSTART updated with the new workflow.
- Spec + 4 sequenced plans under docs/superpowers/.
```

User decides whether to land as 4 commits or 1.
