# Design: Slice 4 — Model-tier eval (isolated, measured)

**Date:** 2026-06-10
**Status:** Approved (brainstorm)
**Parent spec:** `2026-06-10-answer-quality-cost-naturalness-design.md` (slice 4)

## Goal

Close out the answer-quality effort with the two changes the parent spec
isolated behind measurement, because both touch model choice rather than
no-behavior-change quick wins:

- **4b** — replace the LLM conflict tiebreak (which only ever fires on a perfect
  all-axes tie) with a deterministic rule, and remove the code it orphans.
- **4a** — build a re-runnable eval harness that compares `flash` vs
  `flash-lite` as the `knowledge_qa_agent` primary on grounded-extraction
  quality, so the model downgrade is a *measured* decision, not a guess.

The two are independent and independently mergeable.

## Sequencing

1. **4b first** — small, pure-logic, no LLM/DB. Clean win; unblocks dead-code
   removal.
2. **4a second** — larger, opt-in, measurement-driven.

Deliverables mirror slices 1–3: this per-slice spec, then a plan folder
`docs/superpowers/plans/2026-06-10-slice4-model-tier-eval/`.

## Non-goals

- No re-chunking / re-ingestion of the knowledge corpus (parent deferred item).
- 4a does **not** itself flip the production model. The `factory.py` swap is a
  separate follow-up commit, made only if the eval report shows parity.
- The eval harness is **not** added to the pytest CI suite (it issues live LLM
  judge calls); only its grader/reporter logic is unit-tested with a mocked
  judge.

---

## 4b — Deterministic all-axes-tie tiebreak

### Why the LLM tiebreak is removable

The LLM tiebreak (`resolution_agent.resolve` → `gateway`) runs **only** when
`compare()` returns `is_decisive=False`, i.e. `first_score == second_score`
across every axis (`trust_level`, corroboration, `fetched_at` presence,
`fetched_at` value, `confidence_score`) between the top option and the first
differing-value challenger (`comparison_agent.py:26-31`). The resolution prompt
instructs the model to return `"high"` confidence **only when one source is
clearly more trustworthy** — which cannot be true when all axes are tied. So on
a genuine tie the call effectively always returns low confidence →
`_unresolved`, while still costing an LLM call. Replacing it with a
deterministic `tie → unresolved` matches today's effective outcome and never
hides a real source disagreement behind an arbitrary pick.

### Change

- **`services/conflict/resolution_agent.py`**
  - `resolve(record, report)` drops the `gateway` parameter and becomes purely
    deterministic:
    - `report.is_decisive and report.ranked_options` → `resolved` (unchanged
      comparison-winner branch).
    - otherwise → `_unresolved(record, "Comparison was not decisive.")`.
  - Remove the LLM branch (`gateway(...)`, confidence check, chosen-source
    lookup) and the now-unused `_find_option` helper.
  - `resolve_cutoff_conflict` is unchanged.
- **`agents/conflict_agent.py`**
  - Drop gateway construction (`build_default_gateway()` for quota), the
    `batch_interpret_conflict_tiebreak` import/call, the `indecisive`/`decisions`
    /`_lookup` wiring. Phase A still builds `(record, report)` pairs; phase C
    becomes a simple loop: `outcome = resolve(record, report)`.
  - Remove the dead `or outcome.used_llm_tiebreaker` clause when building
    `state.conflicts` (line 84) — unresolved outcomes are already captured by
    `status == "unresolved"`.
- **`services/conflict/resolution_inference_service.py`** — **delete the whole
  module.** Both `interpret_conflict_tiebreak` (single, named by the parent
  spec) and `batch_interpret_conflict_tiebreak` (its only caller was
  `conflict_agent`) become dead, along with `RESOLUTION_SYSTEM_PROMPT` and
  `BATCH_RESOLUTION_SYSTEM_PROMPT`.
- **`services/inference/factory.py`** — remove the now-unused `resolution_agent`
  registry entry (lines 23-29). It was the only consumer of that agent name.
- **`services/conflict/models.py`** — remove the `used_llm_tiebreaker` field and
  the `decision_axes=["llm_tiebreaker"]` usage. Grep confirms no reader outside
  `conflict_agent` and tests; nothing serializes/traces it. (Removal chosen for
  cleanliness; the field is otherwise permanently `False`.)

### Tests

- Delete `tests/services/conflict/test_resolution_inference_service.py` (module
  deleted).
- Rewrite `tests/agents/test_conflict_agent.py`: remove/replace the LLM-tiebreak
  cases (`:98`, `:102`, `:148`) that monkeypatch `batch_interpret_*` and assert
  `used_llm_tiebreaker and status == "resolved"`. Replace with a case asserting
  a genuine all-axes tie resolves to `unresolved` and marks the field uncertain.
- Update `tests/services/conflict/test_resolution_agent.py` for the new
  `resolve()` signature.
- Add an assertion that a tie path issues **zero** LLM calls (a gateway that
  raises if invoked, or a call counter).

### Acceptance

- Tied conflicts resolve to `unresolved` deterministically and reproducibly with
  **no** LLM call.
- Cutoff conflict path unchanged.
- Full `pytest -q` green against `admission_test`.

---

## 4a — Knowledge-QA model-downgrade eval harness

### Key isolation insight

In `qa_service.answer()`, retrieval (embed + `vector_search` +
national-augment) is identical regardless of model — only `_generate` (the
`knowledge_qa_agent` LLM call) depends on the model tier. So the eval **freezes
retrieval** and varies only the generation model, isolating the model-tier
variable exactly as the parent spec intends.

### Location & invocation

- New opt-in package: `eval/knowledge_qa/` (top-level `eval/`, kept out of the
  pytest test paths — it issues live LLM judge calls).
- Run: `python -m eval.knowledge_qa.run` → writes a dated report.

### Units (each independently testable)

1. **Golden set** — `eval/knowledge_qa/golden_set.json`, versioned. One entry
   per case:
   - `question` (Vietnamese), `school`, `topic`.
   - `chunks` — the retrieved chunks **snapshotted at curation time** (frozen
     substrate; the eval feeds these straight into generation, no DB at run
     time).
   - `expected_answer_points` — the facts a correct answer must contain.
   - `expected_source_ids` — the chunk indices a faithful answer should cite.
   - `abstain` — `true` for cases where the chunks lack the info and the model
     **should** return an empty answer (`has_data=False`).
   - **Sourcing:** LLM-drafted from real corpus chunks, then **human-verified**
     before lock. Target ≥30 cases, deliberately including abstention cases.
2. **Runner** — for each case, feed `chunks` directly into a generation step
   (the `_generate` logic, bypassing retrieval) for **flash** and **flash-lite**,
   collecting each `KnowledgeQAResult` (answer, citations, has_data).
3. **Grader (hybrid)** — per (case, model):
   - **Deterministic:** citation-id overlap of returned citations vs
     `expected_source_ids`; abstention-correctness (empty answer iff `abstain`).
   - **LLM judge** (strong model, `flash`): faithfulness (answer uses only the
     provided chunks, no outside info) + factual correctness vs
     `expected_answer_points`. Judge is itself fixed to `flash` so it doesn't
     confound the comparison.
4. **Reporter** — aggregate per-model metrics (faithfulness rate, correctness
   rate, citation accuracy, abstention accuracy) + per-case diffs; write
   `docs/superpowers/evals/2026-06-10-knowledge-qa-flash-vs-flash-lite.md`; print
   a parity verdict.

### Decision rule (the gate)

Adopt `flash-lite` as the `knowledge_qa_agent` **primary** only if it:
- matches or beats `flash` on **faithfulness** and **abstention** (no added
  hallucination), and
- is within a small tolerance on **factual correctness** and **citation
  accuracy**.

The `factory.py` primary-model swap (`knowledge_qa_agent.primary_model:
gemini-2.5-flash → gemini-2.5-flash-lite`) is a **separate follow-up commit**,
made only if the report passes. If it does not pass, the harness and report are
still committed (negative result documented) and the model stays on `flash`.

### Tests

- Unit-test the grader (deterministic checks + a **mocked** judge) and the
  reporter aggregation — verifying the harness without burning LLM calls.
- The model comparison run itself is manual and documented, not a CI test.

### Acceptance

- Documented eval results committed under `docs/superpowers/evals/`.
- `factory.py` primary-model change merged **only** on demonstrated quality
  parity; otherwise the negative result is recorded and no model change ships.

---

## Testing strategy (slice-level)

- 4b ships with unit tests asserting deterministic tie→unresolved and a
  zero-LLM-call guard; full `pytest -q` green.
- 4a ships with unit tests for grader + reporter (mocked judge); the live model
  comparison is a manual, documented eval.

## Delivery order

4b → 4a. Each is independently mergeable. The `factory.py` model swap is gated
on the 4a report and lands as its own commit (or not at all).
