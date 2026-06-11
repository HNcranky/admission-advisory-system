# Slice 4 — Model-tier eval — Plan Index

**Spec:** `docs/superpowers/specs/2026-06-10-slice4-model-tier-eval-design.md`
**Parent spec:** `docs/superpowers/specs/2026-06-10-answer-quality-cost-naturalness-design.md`

Slice 4 has two independent workstreams. They are split into four bite-sized
plans, delivered in order. Each plan ends green (`pytest -q`) and is
independently mergeable.

| # | Plan | Workstream | What it delivers |
|---|------|-----------|------------------|
| 01 | `01-4b-deterministic-tiebreak.md` | 4b | `resolve()` becomes pure-deterministic (tie → unresolved); LLM tiebreak path removed |
| 02 | `02-4a-golden-set-schema-and-loader.md` | 4a | `GoldenCase` model + JSON loader + seed fixture |
| 03 | `03-4a-grader.md` | 4a | Hybrid grader: deterministic citation/abstention checks + LLM judge |
| 04 | `04-4a-runner-reporter-cli.md` | 4a | Model-forced runner, report aggregation, `python -m eval.knowledge_qa.run` CLI |
| 05 | `05-4a-curate-run-document.md` | 4a | Curate ≥30 cases, run the eval, document results, gated `factory.py` swap |

## Delivery order

01 (4b, standalone) → 02 → 03 → 04 → 05 (4a, in sequence).

Plan 01 is fully independent of 02–05 and can merge first. The `factory.py`
model swap is gated on the Plan 05 eval report and lands as its own commit (or
not at all).

## Conventions

- TDD: failing test → run-fail → minimal impl → run-pass → commit.
- Commit messages: no `Co-Authored-By` / AI attribution (repo rule in
  `CLAUDE.md`). Never `git push`.
- Eval harness lives under top-level `eval/` and is **not** in the pytest test
  paths (it issues live LLM calls). Its unit tests live under `tests/eval/` and
  use mocked gateways.
