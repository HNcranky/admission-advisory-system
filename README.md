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
