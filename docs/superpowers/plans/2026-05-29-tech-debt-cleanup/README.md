# Tech-debt Cleanup & Inference Hardening — plan index

Implements `docs/superpowers/specs/2026-05-29-tech-debt-cleanup-design.md`.

The work is split into six small, independently-implementable slices. Execute **in order** — later slices depend on earlier ones (the dependency column says how). Each slice is its own commit (or small commit cluster) on branch `chore/stabilize-cleanup`; open one PR at the end.

| # | Slice | Spec items | Depends on | Risk |
|---|---|---|---|---|
| 01 | [Pydantic v2 + dead-code removal](./01-pydantic-and-dead-code.md) | C1, C2 | — | none (no behaviour change) |
| 02 | [Safety & observability logging](./02-safety-logging.md) | B1, B2, B3 | — | low |
| 03 | [Gemini provider hardening](./03-provider-hardening.md) | A1 | — | medium (changes provider contract) |
| 04 | [Graceful degradation at LLM call sites](./04-graceful-degradation.md) | A2 | 03 | medium |
| 05 | [Inference telemetry wiring](./05-telemetry-wiring.md) | A3 | 03 | low |
| 06 | [Activate the LLM conflict tiebreaker](./06-conflict-tiebreaker.md) | A4 | 03, 04 | medium (adds LLM behaviour) |

Slices 01 and 02 are independent and could be done in any order. Slice 03 introduces `InferenceError` and the `STRUCTURE_FAILURE` contract that 04, 05, and 06 rely on, so it must land before them. Slice 06 relies on 04's degradation guards being in place.

## Shared setup (run once before testing)

All tests run against the Docker Postgres DB to match the verified baseline:

```bash
docker compose up -d --wait db
.venv/Scripts/python.exe -m db.setup_db
```

Use `.venv/Scripts/python.exe -m pytest ...` for every test command in the slices.

## Final verification (after slice 06)

- [ ] **Run the entire suite with the DB up**

```bash
docker compose up -d --wait db
.venv/Scripts/python.exe -m db.setup_db
.venv/Scripts/python.exe -m pytest -q
```
Expected: ≥ prior 174 passed (plus the new tests), 1 skipped (`requires_real_dataset`), 0 failures, and no `PydanticDeprecatedSince20` warnings from the two migrated files.

- [ ] **Open the PR**

```bash
git push -u origin chore/stabilize-cleanup
gh pr create --base main --title "Tech-debt cleanup & inference hardening" \
  --body "Implements docs/superpowers/specs/2026-05-29-tech-debt-cleanup-design.md"
```

## Spec → slice coverage

C1→01, C2→01, B1→02, B2→02, B3→02, A1→03, A2→04, A3→05, A4→06. All eight spec items covered.
