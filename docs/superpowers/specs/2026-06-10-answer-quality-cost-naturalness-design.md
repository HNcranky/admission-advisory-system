# Design: Answer Quality, Cost & Naturalness Improvements

**Date:** 2026-06-10
**Status:** Approved (decomposition + product decisions)

## Goal

Improve the advisory chat assistant across three axes without regressing
behavior:

1. **Cost** — cut LLM spend on the per-turn hot path (thinking tokens,
   redundant calls, duplicate embeddings, wasted retries).
2. **Naturalness** — make Vietnamese responses feel like one coherent advisor
   voice instead of stitched-together templates.
3. **Quality / latency** — better retrieval on follow-ups, fewer DB round-trips,
   cleaner citations.

## Product decisions (locked)

- **Voice register:** the bot refers to itself as **"mình"** and addresses the
  user as **"bạn"**, consistently everywhere. (Neutral/polite, does not assume
  the user is a 12th-grader vs. a parent.)
- **Delivery order:** **cost first**, then naturalness, then RAG, then model-tier
  eval.
- **Model-tier downgrades** (e.g. flash → flash-lite) are isolated into their own
  slice and gated behind a small eval set — never bundled with the
  no-behavior-change quick wins.

## Non-goals

- No table-aware re-chunking of the knowledge corpus in this effort (requires
  re-ingestion; tracked as deferred item 2d).
- No new conversation features (e.g. multi-turn memory beyond what exists).
- No prompt-caching/`cached_content` infrastructure yet (flagged as future work).

## Source of findings

Three parallel read-only reviews (inference/cost, chat/naturalness,
RAG/conflict) on 2026-06-10. Findings cited inline by `file:line` below.

---

## Slice 1 — Cost quick wins (no behavior change, low risk) — FIRST

Goal: reduce per-turn LLM spend without changing any user-visible output.

### 1a. Disable Gemini 2.5 "thinking" (per-agent override)
- **Now:** `services/inference/providers/gemini_provider.py:50-55` builds
  `GenerateContentConfig` with no `thinking_config`. All models are Gemini 2.5
  (flash-lite, flash), which default to thinking ON → billed thinking tokens on
  every call.
- **Change:** set `thinking_config=types.ThinkingConfig(thinking_budget=0)` by
  default. Allow a per-agent override via the model `registry.py` so a future
  agent (e.g. knowledge QA / synthesis) can opt into a small thinking budget if
  an eval shows it helps. Default budget = 0 everywhere initially.
- **Acceptance:** all existing tests pass; a unit test asserts the provider sets
  `thinking_budget=0` when no override is given, and honors an override when the
  registry supplies one.

### 1b. Gate intent router behind deterministic classifier
- **Now:** `conversation_service.py:79` runs `extract_profile` (LLM), then
  `:109` `intent_router.classify` runs a *second* LLM call every turn. The
  router already has a deterministic keyword table (`_FALLBACK_*`,
  `intent_router.py:176-199`) but only as a fallback.
- **Change:** before the LLM classify call, try (1) a cheap-path gate for bare
  slot answers (mirror the extractor's existing gate at `extractor.py:110`), and
  (2) the deterministic keyword table. Only call the LLM on a miss.
- **Acceptance:** keyword-matchable and bare-slot messages produce identical
  `IntentResult` to today with zero LLM calls (assert via a mocked gateway call
  counter); ambiguous messages still hit the LLM and behave as before.

### 1c. Deduplicate question embeddings across knowledge fan-out
- **Now:** `knowledge_fanout.py:35-58` creates N tasks per (school, topic);
  `qa_service.py:55` re-embeds the same `question` each call. National-scope
  augmentation (`qa_service.py:73-80`) runs a second vector search per call whose
  result is query-identical across schools.
- **Change:** embed the question once in `run_knowledge_fanout` (or a per-request
  memo keyed on the text + task type) and pass the vector into `answer()`; run
  the national search once per question and merge into each task's results.
  `answer()` keeps a fallback to embed internally when no vector is supplied
  (preserves the qa_service public contract / standalone callers).
- **Acceptance:** a 3-school × 2-topic query issues **1** `RETRIEVAL_QUERY`
  embedding and **1** national search (assert via mocked embedder/repository
  counters); answer content per (school, topic) unchanged.

### 1d. Structured output schema for JSON calls
- **Now:** `gemini_provider.py:53` sets only `response_mime_type`; JSON shape is
  described in free-text prompts. Malformed JSON → `STRUCTURE_FAILURE`
  (`gemini_provider.py:73-77`) → wasteful same-prompt retry (`gateway.py:22-33`).
- **Change:** pass a `response_schema` for the structured call sites that already
  have a target shape (`IntentResult`; profile extractor; conflict tiebreak).
  Plumb an optional schema through the gateway/provider. On `STRUCTURE_FAILURE`
  with a schema present, prefer falling back rather than retrying the identical
  prompt.
- **Acceptance:** schema-backed calls return validated objects; a malformed
  response no longer triggers an identical-prompt retry; existing fallbacks still
  fire on hard `InferenceError`.

### 1e. Register `major_resolver` + cap tokens
- **Now:** `profile/major_resolver.py:99` calls `gateway.run(agent_name=
  "major_resolver", ...)` but `factory.py` has no override → inherits defaults
  (no `max_tokens`).
- **Change:** add a `major_resolver` registry entry (cheap model, small
  `max_tokens` ≈ 100, explicit retries/fallback) since output is a tiny
  `{"program_ids":[...]}`.
- **Acceptance:** resolver behaves identically on valid input; latency/token
  ceiling bounded.

---

## Slice 2 — RAG / latency correctness (low–medium risk)

### 2a. Batch conflict evidence DB lookups
- **Now:** `conflict/evidence_agent.py:33-38` opens a new psycopg2 connection
  per evidence option (`get_cursor` → fresh connect,
  `ingestion/storage/db_connection.py:28-36`); `package_evidence` loops options
  and `agents/conflict_agent.py:46-50` loops every quota conflict → dozens of
  connections per advisory run.
- **Change:** batch the `fetched_at` lookup into one query
  (`WHERE source_url = ANY(%s) AND school_id=%s AND admission_year=%s`) reusing a
  single connection per record (or one across all records).
- **Acceptance:** same enrichment output; connection/query count drops to O(1)
  per record (asserted via a counting connection factory).

### 2b. Narrow citation fallback
- **Now:** `qa_service.py:122-123` cites **every** retrieved chunk when the LLM
  returns no/invalid `used_source_ids` (up to 8 with national augmentation).
- **Change:** fall back to only the top-1 highest-score chunk (or none).
- **Acceptance:** unit test on the fallback path returns ≤1 citation.

### 2c. Fold conversation context into the embedded query
- **Now:** `qa_service.py:55-63` embeds the raw question; conversation context is
  only prepended to the *generation* prompt (`:139-140`), so follow-ups
  ("còn học phí thì sao?") embed without their referent.
- **Change:** build a condensed retrieval query that incorporates recent
  conversation context (lightweight rewrite or context concatenation) for the
  embedded text. Keep it cheap (string-level/condensed; no extra LLM call unless
  measured worthwhile).
- **Acceptance:** a follow-up question with an elided subject retrieves the
  referent's chunks in a test fixture; standalone questions unchanged.

### 2d. (Deferred) Table-aware chunking — out of scope here, tracked only.

---

## Slice 3 — Naturalness / voice

Apply the locked register: bot = **"mình"**, user = **"bạn"**.

### 3a. Unify pronouns
- **Now:** final advisory uses "em" (`services/explanation_service.py:60,116,
  138,175,221`); profile/small-talk uses "bạn" (`profile/slots.py:55-61`,
  `chat/conversational_handler.py:3-35`, `conversation_service.py` clarification/
  ready/knowledge strings, `web/static/js/modules/messages.js:60-61,76`). Single
  turns mix both (`conversation_service.py:297` "bạn" vs advisory "em").
- **Change:** rewrite all user-facing strings to bot="mình", user="bạn".
- **Acceptance:** no user-facing string contains "em" as the addressee; a grep
  guard test (or string audit) passes.

### 3b. Fix de-accented error message
- **Now:** `chat/run_dispatcher.py:51` is ASCII: "Xin loi, qua trinh phan tich
  bi gian doan. Ban hay thu lai."
- **Change:** proper diacritics: "Xin lỗi, quá trình phân tích bị gián đoạn. Bạn
  thử lại giúp mình nhé."

### 3c. Acknowledge captured slots before next question
- **Now:** `conversation_service.py:278-295` asks one bare `follow_up` per turn
  (`slots.py:55-61`) with no reaction to the value just captured.
- **Change:** echo/confirm the newly captured value (available in `delta`/
  `merged`) before the next ask; when ≥2 slots are filled, prepend a one-line
  recap of what's understood and what's still needed. Soften the
  `admission_method` prompt (`slots.py:57`).
- **Acceptance:** when a turn captures a value, the response references it before
  asking the next slot (fixture assertion).

### 3d. Vary closing question + personalize intro
- **Now:** `explanation_service.py:58-61` `CLOSING_QUESTION` appended verbatim
  every advisory (`:374-376`); `_intro_paragraph` (`:121-142`) is a flat comma
  list.
- **Change:** rotate among a few closing variants and skip it on a
  follow-up/correction re-run within the same session; have the intro react to
  the score band/margin (data already in `renderable`).
- **Acceptance:** consecutive advisories in one session don't repeat the same
  closing line; intro wording differs by score band in fixtures.

### 3e. De-duplicate conflict caveats + add transitions
- **Now:** `_data_note` (`explanation_service.py:207-234`) and reasoning cautions
  (`reasoning_service.py:101-109`) emit the same dense caveat per program; bare
  bold section headers with no connective lead-ins (`:317-366`).
- **Change:** summarize the data-conflict caveat once near the top when multiple
  programs conflict; shorten the repeated "kiểm tra thông báo tuyển sinh chính
  thức" boilerplate; add one-line bridges before sections like "Không đủ điều
  kiện xét tuyển".
- **Acceptance:** with N conflicting programs the full caveat appears once, not N
  times.

### 3f. Empathy-first + register unification for small talk
- **Now:** `EMOTIONAL_SUPPORT` (`conversational_handler.py:31-35`) pivots
  straight to a data request; "no data" fallbacks say cold "Hệ thống chưa có
  dữ liệu" (`conversation_service.py:339-342`, `knowledge_fanout.py:84-87`).
- **Change:** lead emotional-support replies with validation, defer the data ask;
  unify knowledge "no data" fallbacks to first-person "Mình hiện chưa có…".
- **Acceptance:** emotional-support reply validates before asking; no
  user-facing "Hệ thống chưa có" remains.

---

## Slice 4 — Model-tier eval (isolated, measured)

### 4a. Knowledge-QA model downgrade trial
- **Now:** `factory.py:32-38` sets `knowledge_qa_agent` primary = flash, with
  flash-lite only as fallback; it's the highest-frequency knowledge call.
- **Change:** assemble a small golden set of Q→expected-grounding cases; compare
  flash vs flash-lite as primary on grounded extraction quality. Switch to
  flash-lite primary only if the eval holds.
- **Acceptance:** documented eval results; change merged only if quality parity.

### 4b. Deterministic all-axes-tie tiebreak
- **Now:** a conflict reaches the LLM only on a perfect tie across all axes
  (`comparison_agent.py:30-31`); the LLM gets the same fields and precedence it
  can't improve on (`resolution_inference_service.py:55-65`).
- **Change:** replace the all-axes-tie LLM tiebreak with a deterministic final
  rule (e.g. highest corroboration → lowest source_url → unresolved). Remove the
  now-dead single-call `interpret_conflict_tiebreak` if only tests use it
  (`resolution_inference_service.py:27`).
- **Acceptance:** tied conflicts resolve deterministically and reproducibly with
  no LLM call; existing conflict tests pass.

---

## Testing strategy

- Each slice ships with unit tests asserting its acceptance criteria (call
  counters via mocked gateway/embedder/connection factories for cost items;
  string/fixture assertions for voice items).
- Full `pytest -q` green against `admission_test` after each slice.
- Slice 4 additionally requires the documented eval before any model change.

## Delivery order

1 → 3 → 2 → 4. Each slice is independently mergeable.
