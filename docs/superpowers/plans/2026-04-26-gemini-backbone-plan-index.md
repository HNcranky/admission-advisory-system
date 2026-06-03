# Gemini Backbone Plan Index

This spec is split into four sequential plans so each slice can ship, pass tests, and leave the repository in a usable state before the next one starts.

## Execution Order

1. `2026-04-26-gemini-backbone-plan-01-inference-foundation.md`
   - Build the shared inference package, Gemini provider adapter, static registry, and gateway contracts.
   - No advisory agent behavior changes in this slice.
2. `2026-04-26-gemini-backbone-plan-02-advisory-agent-migration.md`
   - Route the LLM-suitable advisory responsibilities through the gateway while keeping retrieval and hard policy checks deterministic.
3. `2026-04-26-gemini-backbone-plan-03-escalation-telemetry-and-uncertainty.md`
   - Add selective fallback, retry classification, cost telemetry, and explicit uncertainty handling.
4. `2026-04-26-gemini-backbone-plan-04-ingestion-and-conflict-expansion.md`
   - Extend the same backbone to the broader ingestion and conflict-resolution architecture without rewriting the completed advisory flow.

## Scope Boundaries

- Plan 1 must merge before Plan 2 starts.
- Plan 2 must leave all current advisory tests green and add new mocked gateway coverage.
- Plan 3 may only enable fallback for `reasoning_agent` and `policy_agent`.
- Plan 4 must reuse the same `services/inference/` package instead of introducing a second model-routing path.
