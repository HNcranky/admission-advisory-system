# Design: Slice 2 — RAG / Latency Correctness

**Date:** 2026-06-10
**Status:** Approved (refined after grounding review)
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
   DB-backed.
2. For the DB-backed set, run **one** query inside a single
   `get_cursor(commit=False)`:

   ```sql
   SELECT car.source_url, rd.fetched_at
   FROM canonical_admission_records car
   LEFT JOIN extracted_facts ef ON ef.id = car.extracted_fact_id
   LEFT JOIN raw_documents rd ON rd.id = ef.raw_document_id
   WHERE car.source_url = ANY(%s)
     AND car.school_id = %s
     AND car.admission_year = %s
   ```

3. Build a `{source_url: fetched_at}` map and assign `option.fetched_at` per
   DB-backed option (options with no row keep their existing value, as today).

Keep the resilience: a DB failure leaves the record's options un-enriched
(wrap the batch in `try/except`, mirroring today's per-option swallow) rather
than crashing the advisory run.

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

**Acceptance:** a unit test driving the fallback path (LLM returns
`used_source_ids = []` / invalid) returns **≤1** citation.

---

## 2c. Fold conversation context into the embedded query (gated + tiny)

**Now:** the embedded text is the raw question, so an elided follow-up
("còn học phí thì sao?") embeds without its referent.

**Change:** add a pure helper
`services/knowledge/retrieval_query.py::build_retrieval_query(question, history_ctx) -> str`:

- Returns `question` **unchanged** unless the question is **elliptical**.
  Ellipsis heuristic (string-level, no LLM call): the question is short
  **and** (it opens with a continuation cue — `còn` / `thế` / `vậy` /
  `thì sao` / `so với` — **or** it contains no school/topic noun). The exact
  rule is tuned against fixtures during implementation; start stricter (require
  a continuation cue) and loosen only if a fixture follow-up is missed.
- When it fires, prepend **only the last user turn** parsed out of
  `history_ctx` (not assistant turns, not the full blob) →
  `f"{prev_user}\n{question}"`. Assistant text is the noisiest thing to embed
  and the most likely to derail retrieval; keeping context tiny stops a long
  history from diluting a short query.

Call sites (the helper finalizes the text **before** any embedding, preserving
slice 1's embed-once):

- `run_knowledge_fanout`: call `build_retrieval_query(content, conversation_context)`
  and pass the result to `embed_query(...)` (and as `question` for the shared
  vector path). The referent is school-agnostic, so the one augmented vector is
  correct for every `(school, topic)` task.
- `_handle_knowledge_qa`: call the helper and pass the result as `answer()`'s
  `question`.
- `answer()` itself is **untouched** — it embeds whatever text it is handed.

**Acceptance:**
- A fixture: an elided follow-up (continuation cue, prior user turn names the
  referent) retrieves the referent's chunks; without the helper it would not.
- A standalone (non-elliptical) question takes the unchanged path and embeds
  byte-for-byte as today (the helper returns the question verbatim) — satisfies
  the parent spec's "standalone questions unchanged".
- `build_retrieval_query` has direct unit tests for the gate (fires on
  elliptical, no-ops on standalone) and the last-user-turn extraction.

---

## Testing strategy

- 2a verified by a connection/query-counting spy + an output-equality fixture.
- 2b verified by the ≤1-citation fallback assertion.
- 2c verified by helper unit tests (gate + extraction) plus a fixture proving
  follow-up retrieval improves and standalone retrieval is unchanged.
- Full `pytest -q` green against `admission_test` after the slice.

## Out of scope (tracked elsewhere)

- **2d Table-aware re-chunking** — requires re-ingestion; deferred in the parent
  spec, not part of this slice.
- LLM-based query rewriting/condensation for 2c — explicitly avoided ("keep it
  cheap"); revisit only if the string-level gate proves insufficient in
  measurement.
- Whole-run (cross-record) evidence batching → rejected above; revisit only if
  conflict record counts grow large.
