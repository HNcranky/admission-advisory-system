# Design: Slice 2 — RAG / Latency Correctness

**Date:** 2026-06-10
**Status:** Approved (refined after grounding + conformance review)
**Parent:** `2026-06-10-answer-quality-cost-naturalness-design.md`

## Goal

Reduce DB round-trips and improve retrieval correctness on the per-turn hot
path. Each item ships with a unit test asserting a call-count or behavior
invariant. No user-visible advisory/answer *content* changes except 2b's
citation set on the (rare) LLM-fallback path.

## Grounding facts (verified 2026-06-10)

- `services/conflict/evidence_agent.py::_enrich_from_db` opens a fresh
  `get_cursor()` (→ new psycopg2 connection, `ingestion/storage/db_connection.py:36`)
  **per evidence option**. `package_evidence` loops a record's options, and
  `agents/conflict_agent.py:46-50` calls `package_evidence` per quota conflict →
  O(#options) connections across a run.
- Mock sources (`mock://…` or `metadata["mock_conflict"]`) are skipped before any
  DB call (`evidence_agent.py:16-19,49`) and must stay skipped.
- `services/knowledge/qa_service.py::_resolve_citations` (`:139-140`) falls back
  to `list(chunks)` — citing **every** retrieved chunk (up to 8 after national
  augmentation) — when the LLM returns no/invalid `used_source_ids`. Chunks are
  already score-sorted after the national merge (`qa_service.py:96`), so
  `chunks[0]` is the highest-score chunk.
- `qa_service.answer()` embeds the raw `question` (`:62`); `history_ctx`
  (`build_history_context`, last 3 user/assistant pairs, each ≤500 chars —
  `services/chat/history.py:10`) is passed only to the **generation** prompt
  (`:106,156-157`), never to the embedding.
- Slice 1 made the fan-out embed the query **once** via `embed_query(content)`
  and share the vector across all `(school, topic)` tasks
  (`services/chat/knowledge_fanout.py:46`). 2c must preserve embed-once: the
  query text has to be finalized **before** `embed_query`.

---

## 2a. Batch conflict evidence DB lookups (per-record) — FIRST

**Now:** one connection + one query per evidence option (see grounding).

**Change:** keep `package_evidence(record, raw_candidates)`'s signature and the
mock-skip behavior. Replace the per-option `_enrich_from_db` with a single
batched lookup per record:

1. Partition `record.options` into mock (passed through unchanged) and
   DB-backed (reusing the existing `_is_mock_source` + `candidates_by_source`
   logic). **If the DB-backed set is empty (all-mock record), skip the query
   entirely — do not open a cursor at all** (an all-mock record must issue zero
   DB calls; `test_package_evidence_uses_candidate_evidence_for_mock_sources`
   asserts `get_cursor` is never called).
2. For the DB-backed set, run **one** query inside a single
   `get_cursor(commit=False)` (note: drops the per-option `LIMIT 1`, so use
   `fetchall()` — see the dedup note below):

   ```sql
   SELECT car.source_url, rd.fetched_at
   FROM canonical_admission_records car
   LEFT JOIN extracted_facts ef ON ef.id = car.extracted_fact_id
   LEFT JOIN raw_documents rd ON rd.id = ef.raw_document_id
   WHERE car.source_url = ANY(%s)
     AND car.school_id = %s
     AND car.admission_year = %s
   ```

3. Build a `{source_url: fetched_at}` map from `fetchall()` and assign
   `option.fetched_at` per DB-backed option (options with no row keep their
   existing value, as today). **Dedup:** without `LIMIT 1`, a `source_url` with
   multiple canonical rows returns multiple rows — collapse to one entry per
   `source_url` (any wins; `fetched_at` is a property of the source document, so
   it is consistent across that URL's rows).

Keep the resilience: a DB failure leaves the record's options un-enriched
(wrap the batch in `try/except`, mirroring today's per-option swallow) rather
than crashing the advisory run.

**Test-fake impact:** existing `test_evidence_agent.py` fakes expose `fetchone`;
the batched code calls `fetchall`, so the fakes need a `fetchall` method.

**Scope:** per-record batching only. Whole-run batching (one query across all
records) was considered and rejected — it would restructure `conflict_agent`'s
Phase A and the `package_evidence` API for marginal gain when the record count
is small.

**Acceptance:**
- Enrichment output (each option's `fetched_at`) is identical to today on a
  fixture with multiple options.
- For a record with K DB-backed options, exactly **1** connection and **1**
  query are issued (was K). Asserted by a counting spy patched over
  `get_connection`/`get_cursor` (module-level helper, so we patch rather than
  inject — same guarantee as the spec's "counting connection factory").
- Mock options still issue **0** DB calls.

---

## 2b. Narrow citation fallback

**Now:** `_resolve_citations` falls back to `list(chunks)` (cite all) when the
LLM names no valid sources but still produced a grounded answer.

**Change:** change the `if not selected:` fallback from `list(chunks)` to
`chunks[:1]` — cite only the top-1 highest-score chunk. The answer is grounded
(non-empty `answer_text`), so the single best-matching source is a reasonable,
non-misleading attribution; the existing dedup loop downstream is unchanged.

**Behavior change (not just a count):** this changes *which* source surfaces on
the fallback path, not only how many. Today the cite-all fallback is what
surfaces a national-scope source when the LLM names no ids and that national
chunk wasn't top-scored. After this change only `chunks[0]` is cited, so such a
national source can drop out of the citation list. This is intended (a fallback
should not attribute the answer to up to 8 chunks the LLM never named), but it
is a real behavior shift, not a mechanical tweak.

**Tests to update:**
- `test_qa_service.py::test_citations_fallback_to_all_chunks_when_used_ids_empty`
  (currently asserts `== 2`) → assert `<= 1`.
- `test_qa_service.py::test_specific_school_query_also_pulls_national_chunks`
  relies on the cite-all fallback to surface the national source; rework it so
  the national chunk is top-scored (or assert the new top-1 behavior).

**Acceptance:** a unit test driving the fallback path (LLM returns
`used_source_ids = []` / invalid) returns **≤1** citation.

---

## 2c. Fold conversation context into the embedded query (gated + tiny)

**Now:** the embedded text is the raw question, so an elided follow-up
("còn học phí thì sao?") embeds without its referent.

**Change:** add a pure helper
`services/knowledge/retrieval_query.py::build_retrieval_query(question, prev_user) -> str`:

- Takes the current `question` and the **previous user message text**
  (`prev_user`) — *not* the rendered `history_ctx` blob. `history_ctx` is a
  role-labeled, 500-char-truncated rendering (`Người dùng:` / `Trợ lý:`); a
  multi-line user message spans several lines with only the first prefixed, so
  re-parsing it for "the last user turn" is lossy. The caller extracts the raw
  prior user message and passes it in (see call sites).
- Returns `question` **unchanged** unless the question is **elliptical** (or
  `prev_user` is empty). Ellipsis heuristic (string-level, no LLM call): the
  question is short **and** (it opens with a continuation cue — `còn` / `thế` /
  `vậy` / `thì sao` / `so với` — **or** it contains no school/topic noun). The
  exact rule is tuned against fixtures; start stricter (require a continuation
  cue) and loosen only if a fixture follow-up is missed.
- When it fires, return `f"{prev_user}\n{question}"` — prepend **only** the
  prior user turn (never assistant text, never the full history). Keeping
  context tiny stops a long history from diluting a short query.

**Embedding-only — must not reach the generation prompt.** The augmented text is
for *retrieval* only. The generation prompt already carries the prior turn via
`conversation_context` (`qa_service.py:156-157`), so feeding the augmented text
in as `question` would duplicate the prior question into the `Câu hỏi:` field and
risk the model answering the *previous* question. Therefore:

- Add an optional `retrieval_query: str | None = None` to `answer()`. When set
  (and no `query_vector` is supplied), embed `retrieval_query` instead of
  `question`; **`question` stays the original `content`** and remains the only
  text in the generation prompt. When both are `None`, behavior is exactly as
  today.

Call sites (the augmented text finalizes **before** embedding, preserving
slice 1's embed-once; `question`/`content` is never mutated):

- `_handle_knowledge_qa`: the raw message list is already fetched upstream
  (`conversation_service.py:71`). Capture it once, derive the prior user message,
  and call `answer(question=content, retrieval_query=build_retrieval_query(content, prev_user), ...)`.
- `run_knowledge_fanout`: today it only receives the rendered
  `conversation_context`. Thread the prior-user text down as a **new
  `prev_user` arg** from `_handle_hybrid`, build the augmented query once, and
  embed *that* via `embed_query(...)`. The fan-out already pre-embeds and shares
  `query_vector`, so it passes the augmented vector through the **existing
  `query_vector` param** (no `retrieval_query` needed here → the fan-out fakes
  stay untouched), while still passing `question=content` (original) to each
  `answer()`. The referent is school-agnostic, so the one augmented vector is
  correct for every `(school, topic)` task. On the embed-fail fallback
  (`query_vector is None`), the fan-out degrades to embedding the original
  `question` internally (augmentation is a best-effort optimization, dropped on
  the rare embed-failure path) — `retrieval_query` is only needed on the single
  no-vector path above.

**Acceptance:**
- A fixture: an elided follow-up (continuation cue, `prev_user` names the
  referent) retrieves the referent's chunks; without the helper it would not.
- A standalone (non-elliptical) question takes the unchanged path and embeds
  byte-for-byte as today (helper returns `question` verbatim) — satisfies the
  parent spec's "standalone questions unchanged".
- The generation prompt's `Câu hỏi:` field is always the original `question`,
  never the augmented text (assert the augmented text does not appear as the
  question in a captured prompt).
- `build_retrieval_query` has direct unit tests for the gate (fires on
  elliptical, no-ops on standalone / empty `prev_user`).

---

## Testing strategy

- 2a verified by a connection/query-counting spy + an output-equality fixture;
  existing `test_evidence_agent.py` fakes updated to expose `fetchall`.
- 2b verified by the ≤1-citation fallback assertion; the two affected
  `test_qa_service.py` tests updated (see 2b).
- 2c verified by helper unit tests (gate + empty-`prev_user` no-op) plus a
  fixture proving follow-up retrieval improves, standalone retrieval is
  unchanged, and the generation prompt's question stays the original `content`.
- Full `pytest -q` green against `admission_test` after the slice.

## Out of scope (tracked elsewhere)

- **2d Table-aware re-chunking** — requires re-ingestion; deferred in the parent
  spec, not part of this slice.
- LLM-based query rewriting/condensation for 2c — explicitly avoided ("keep it
  cheap"); revisit only if the string-level gate proves insufficient in
  measurement.
- Whole-run (cross-record) evidence batching → rejected above; revisit only if
  conflict record counts grow large.
