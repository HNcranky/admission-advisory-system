# Conflict-Aware Advisory V1 Plan Index

> **For agentic workers:** Execute these plans in order. Do not create commits unless the user explicitly asks.

This plan set implements spec `docs/superpowers/specs/2026-05-13-conflict-aware-advisory-v1-design.md` after the mock retrieval amendment.

## Execution Order

1. `2026-05-13-conflict-aware-advisory-slice-1-mock-retrieval.md`
   - Adds `ADVISORY_MOCK_CONFLICTS=1`.
   - Guarantees mock retrieval returns stable conflicting `CandidateProgram` rows without touching DB.

2. `2026-05-13-conflict-aware-advisory-slice-2-schema-and-real-dataset.md`
   - Changes `canonical_admission_records` uniqueness to per-source rows.
   - Defines the real-data SQL acceptance gate and fixture export path.

3. `2026-05-13-conflict-aware-advisory-slice-3-models-and-detection.md`
   - Adds structured conflict models.
   - Adds deterministic quota-conflict detection.
   - Moves conflict responsibility out of `retrieval_agent`.

4. `2026-05-13-conflict-aware-advisory-slice-4-resolution-graph-and-surfacing.md`
   - Adds evidence packaging, comparison, resolution, source labels, graph wiring, reasoning downgrade, and `Xac minh du lieu` final-answer surfacing.
   - Adds mock-driven graph integration coverage.

5. `2026-05-13-conflict-aware-advisory-slice-5-real-e2e-and-docs.md`
   - Adds the opt-in `requires_real_dataset` gate.
   - Documents mock demo and real-data completion commands.

## Acceptance Summary

- Mock path acceptance: `ADVISORY_MOCK_CONFLICTS=1` graph test passes and final answer contains `Xac minh du lieu` without a retrieval DB call.
- Real-data acceptance: `pytest -m requires_real_dataset -v` passes against the curated HUST/VNU-UET fixture and final answer contains `Xac minh du lieu`.
- Production path acceptance: with `ADVISORY_MOCK_CONFLICTS` unset, retrieval continues to use Postgres.
