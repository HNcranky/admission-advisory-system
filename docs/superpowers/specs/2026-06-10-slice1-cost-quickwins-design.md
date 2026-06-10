# Design: Slice 1 — Cost Quick Wins

**Date:** 2026-06-10
**Status:** Approved (refined after grounding review)
**Parent:** `2026-06-10-answer-quality-cost-naturalness-design.md`

## Goal

Reduce LLM/embedding spend on the per-turn hot path. Each item ships with unit
tests asserting a call-count or behavior invariant. No user-visible output
changes except where explicitly noted (none in this slice).

## Grounding facts (verified 2026-06-10)

- `services/inference/factory.py` default model is `gemini-2.5-flash-lite`. Only
  `knowledge_qa_agent` and `synthesis_agent` use `gemini-2.5-flash` as primary
  (`resolution_agent`/`knowledge_ocr` use flash only as fallback).
- **Gemini 2.5 Flash-Lite does not think by default** (min budget 512, cannot be
  0). **Gemini 2.5 Flash defaults to dynamic thinking** and can be disabled with
  `thinking_budget=0`. Pro cannot disable thinking (unused here).
  Source: https://ai.google.dev/gemini-api/docs/thinking
  → Disabling thinking only saves money on the two **flash** agents, which are
  also the quality-sensitive ones (grounded QA, prose synthesis). Thinking is a
  no-op on every flash-lite agent.
- `InferenceRequest` already carries an (unused) `schema_name: Optional[str]`
  field (`services/inference/models.py:16`) — structured-output plumbing is
  partially laid.
- The knowledge fan-out runs tasks on a `ThreadPoolExecutor`
  (`services/chat/knowledge_fanout.py`) — any shared embedding cache would need
  locking; precomputing avoids that.

## Execution order

After grounding (reading `conversation_service.py`), **1b is dropped** — its safe
win is already implemented (see below). Final plan set, split into small plans:

All plans live under `plans/2026-06-10-slice1-cost-quickwins/`:

- Plan A — 1c query-embedding dedup (`slice1a-embedding-dedup.md`)
- Plan B — 1c national-search dedup (`slice1b-national-search-dedup.md`)
- Plan C — 1a per-agent thinking budget (`slice1c-thinking-budget.md`)
- Plan D — 1e major_resolver registry (`slice1d-major-resolver-registry.md`)
- Plan E — 1d response_schema, robustness/last (`slice1e-response-schema.md`)

---

## 1c. Deduplicate question embeddings across knowledge fan-out — FIRST

**Now:** `knowledge_fanout.py:35-58` creates N tasks per `(school, topic)`;
`qa_service.py:55` re-embeds the same `question` (`RETRIEVAL_QUERY`) on every
`answer()` call. National-scope augmentation (`qa_service.py:73-80`) runs a
second vector search per call whose embedding is query-identical across schools.
A 3-school × 2-topic query issues 6 identical query embeddings + 6 national
searches.

**Change:**
- Add an optional `query_vector: list[float] | None = None` parameter to
  `qa_service.answer()`. When supplied, skip the internal embed and use it for
  both the school search and the national search. When `None`, embed internally
  (preserves the existing public contract for standalone callers).
- In `run_knowledge_fanout`, embed the question **once** (`RETRIEVAL_QUERY`) and
  pass that vector into every per-task `answer()` call.
- Run the national-scope vector search **once per question** in the fan-out (or
  expose a way for `answer()` to receive a precomputed national result set);
  merge the shared national chunks into each `(school, topic)` task's results.

**No shared mutable cache** — precompute the vector before dispatching threads.

**Acceptance:**
- A mocked embedder counter shows **1** `RETRIEVAL_QUERY` embed for an
  N-school × M-topic query (was N×M).
- A mocked repository counter shows **1** national-scope search per question
  (was N×M).
- Answer content per `(school, topic)` is byte-identical to today on a fixture.

---

## 1b. Cheap-path intent routing for bare slot answers — DROPPED (already done)

**Finding (grounding, `conversation_service.py:98-100`):** the safe win 1b
targeted is **already implemented**. `handle_user_message` calls
`_maybe_continue_advisory` **before** `intent_router.classify`; when a bare slot
answer fills the pending slot it returns immediately, so the intent router LLM
is **never** called for that turn. Extraction's own LLM is likewise gated for
bare answers (`extractor.py:110`). The remaining double-call only happens on
genuinely intent-bearing messages (greetings, knowledge questions, advisory
triggers) where the LLM router is the right tool.

The only further saving would be promoting the keyword table to a primary
classifier — explicitly rejected (semantic-change risk). **No plan written.**

**Separate follow-up (not 1b):** a greeting like "xin chào" still runs profile
extraction (and can trigger a major-resolver Tier-2 embedding) before routing —
up to 3 calls for one greeting, because extraction runs before intent routing.
Tracked as a future investigation; larger than this slice.

---

## 1a. Per-agent thinking budget (infra) + disable on knowledge_qa

**Now:** `gemini_provider.py:50-55` builds `GenerateContentConfig` with no
`thinking_config`; flash agents bill dynamic-thinking tokens on every call.

**Change (two parts):**
1. **Infra (no behavior change):** add an optional `thinking_budget: int | None`
   to `InferencePolicy` (`models.py`) / `ModelRegistry.resolve`
   (`registry.py`). When set, the provider passes
   `thinking_config=types.ThinkingConfig(thinking_budget=<n>)` in
   `GenerateContentConfig`. When unset, behavior is exactly as today (no
   `thinking_config`).
2. **Apply:** set `thinking_budget=0` on `knowledge_qa_agent` in `factory.py`
   (grounded extractive QA — thinking adds little, real flash savings).
   **Leave `synthesis_agent` unchanged** (generative Vietnamese prose;
   naturalness is a project goal — deferred to Slice 4 eval before any change).

**Acceptance:**
- Unit test: provider sets `thinking_budget=0` for `knowledge_qa_agent` and sets
  **no** `thinking_config` for an agent with no override (e.g. `profile_agent`).
- `synthesis_agent` still sends no `thinking_config`.
- Existing QA tests pass (output shape unchanged).

---

## 1e. Register `major_resolver` + cap tokens

**Now:** `profile/major_resolver.py:99` calls `gateway.run(agent_name=
"major_resolver", ...)` but `factory.py` has no override → inherits defaults
(flash-lite, `max_retries=1`, **no `max_tokens`**).

**Change:** add a `major_resolver` entry to `agent_overrides`:
`{"output_mode": "json", "max_retries": 1, "max_tokens": 100}` (output is a tiny
`{"program_ids": [...]}`). Confirm flash-lite is the intended model.

**Acceptance:** resolver returns the same `program_ids` on a fixture; the
request's `max_tokens` is bounded (asserted via a capturing provider).

---

## 1d. Structured-output schema for intent + profile_extractor (robustness, last)

> Flagged as **robustness, not cost** — `STRUCTURE_FAILURE` retries are rare at
> `temperature=0` on flash-lite. Lowest priority in this slice; safe to drop
> under time pressure without affecting the cost wins above.

**Now:** `gemini_provider.py:53` sets only `response_mime_type`; JSON shape is
described in free-text prompts. Malformed JSON → `STRUCTURE_FAILURE`
(`gemini_provider.py:73-77`) → same-prompt retry (`gateway.py:22-33`).

**Change:**
- Plumb an optional response schema through the gateway/provider (use the
  existing `schema_name` field or add a `response_schema` to the request),
  passed as `response_schema` in `GenerateContentConfig`.
- Apply to `intent_router` (`IntentResult` shape, already a Pydantic model) and
  `profile_extractor` only. Keep the prompt's JSON description as belt-and-
  suspenders.
- On `STRUCTURE_FAILURE` when a schema is present, prefer falling back over
  retrying the identical prompt.

**Acceptance:**
- Schema-backed calls return validated objects on a fixture; a forced malformed
  response no longer triggers an identical-prompt retry.
- Agents without a schema are completely unaffected.

---

## Testing strategy

- Cost items (1c, 1b, 1a, 1e) are verified by **call/connection counters** on
  mocked gateway / embedder / repository, plus output-equality fixtures proving
  no behavior change.
- 1d verified by validated-object fixtures + the no-retry assertion.
- Full `pytest -q` green against `admission_test` after the slice.

## Out of scope (tracked elsewhere)

- Disabling thinking on `synthesis_agent` → Slice 4 (eval-gated).
- Keyword-first primary classifier / merged extraction+routing call → future.
- Prompt/context caching (`cached_content`) → future.
