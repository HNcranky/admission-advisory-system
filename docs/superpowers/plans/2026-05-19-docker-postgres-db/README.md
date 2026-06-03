# Docker Postgres DB Migration — Plan Index

**Spec:** [`docs/superpowers/specs/2026-05-19-docker-postgres-db-design.md`](../../specs/2026-05-19-docker-postgres-db-design.md)

**Date:** 2026-05-19

**Total plans:** 4. Execute strictly in order; each plan depends on outputs of the previous one.

| # | Plan | Outcome | Estimated time |
|---|---|---|---|
| 01 | [Compose Foundation](./01-compose-foundation.md) | `docker compose up -d db` starts healthy Postgres; host app can connect to `localhost:5432` with default `.env` | 30–45 min |
| 02 | [Migration Idempotency](./02-migration-idempotency.md) | `python -m db.setup_db` is safe to re-run; migration 010 patched to be idempotent | 15–25 min |
| 03 | [Integration Test Infrastructure](./03-integration-test-infrastructure.md) | `pytest -m integration` runs E2E pipeline-to-DB smoke tests; auto-skips when DB unreachable | 45–60 min |
| 04 | [Documentation & Final Acceptance](./04-documentation-and-acceptance.md) | README has Docker setup section; all 10 spec acceptance criteria pass | 20–30 min |

## Conventions across plans

- **No git commits inside plan steps.** The user will commit manually when satisfied with a milestone. Each plan ends with a `Commit checklist` listing the exact files staged and a suggested commit message, but the `git commit` invocation is **NOT** a checklist step — the user runs it themselves.
- **TDD where behavior is testable.** Pure infra steps (creating YAML/env files) use command-output verification instead of unit tests; behavior changes (migration patch, fixtures) use proper tests-first flow.
- **Verification commands are mandatory.** Every implementation step is followed by an explicit verification step with expected output. If the verification fails, stop and diagnose — do not proceed to the next step.
- **Files are referenced by absolute repo-relative path.** No ambiguous "the parser file" wording.

## Pre-flight before starting

1. Docker Desktop (or compatible runtime) installed and running. Verify: `docker version` exits 0.
2. Python venv active for the repo. Verify: `python -c "import psycopg2"` exits 0.
3. Working tree clean OR on a feature branch. Verify: `git status`.
4. If `postgresql-x64-18` Windows service is currently running and using port 5432, stop it first: `Stop-Service postgresql-x64-18`. Otherwise port 5432 will be taken.
