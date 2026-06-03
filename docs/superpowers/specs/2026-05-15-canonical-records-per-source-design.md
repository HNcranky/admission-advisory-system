# Canonical Records Per-Source Coexistence + Q&A Strategy Note

## Summary

Two narrow, foundational changes plus one written note that together unblock the rest of the conflict-aware advisory program:

1. **Schema migration** that lets two sources reporting the same logical program coexist as two rows in `canonical_admission_records` instead of one source silently overwriting the other.
2. **Writer change** in `ingestion/storage/db_writer.py:save_canonical_records` that uses the new uniqueness key as its `ON CONFLICT` target.
3. **Q&A strategy note** committed alongside the spec, locking in the V1 answer to "is the database ready for the agent to query?" — yes for structured advisory, no for open-ended student Q&A — and sketching the future RAG slice's plug-in points.

This is the foundation spec. VNU-UET ingestion (`2026-05-15-vnu-uet-ingestion-design.md`) and NEU ingestion (`2026-05-15-neu-ingestion-design.md`) depend on it. The downstream conflict-aware advisory spec (`2026-05-13-conflict-aware-advisory-v1-design.md`) also depends on it; this spec replaces the schema-migration and writer-change items from that spec's Slice 1.

## Problem Statement

### The writer destroys the conflict signal

The current schema enforces `UNIQUE(school_id, admission_year, program_id, admission_method)` on `canonical_admission_records` (`db/migrations/005_canonical_programs.sql:23`). The writer's upsert uses that exact tuple as its `ON CONFLICT` target (`ingestion/storage/db_writer.py:181`). The effect: when a second source reports the same logical program, its row overwrites the first source's row instead of coexisting alongside it.

That means the conflict signal the rest of the project depends on — two sources disagreeing on a value for the same program — is destroyed at the storage layer before any downstream code can see it. The conflict-aware advisory spec, the VNU-UET ingestion spec, and the NEU ingestion spec all assume per-source coexistence. None of them can demonstrate anything until this is fixed.

### The "is the database ready?" question has no written answer

The advisory agent currently does structured SQL retrieval over `canonical_admission_records` and returns typed `CandidateProgram` objects (`services/retrieval_service.py:47`). That works for the structured advisory use case the conflict-aware spec targets. It does not work for open-ended student questions ("what scholarships does HUST offer?", "what's the early-admission deadline at UET?") because the data those questions need lives in the source text body — captured in `raw_documents.parsed_text` but never indexed for semantic retrieval.

Without a written answer, two risks materialize:
- Subsequent spec work might either (a) over-design for Q&A it doesn't need or (b) accidentally close off the future RAG path by dropping `raw_documents.parsed_text` or restructuring it in a way that's hard to reverse.
- The thesis defense lacks a clear statement of which capability is in V1 and which is a later slice.

The Q&A strategy note in this spec is the written answer.

## Goals

- Ship `db/migrations/010_canonical_records_per_source.sql` that drops the old uniqueness constraint and adds the new per-source one.
- Update `ingestion/storage/db_writer.py:save_canonical_records` to use the new `ON CONFLICT` target. No other writer logic changes.
- Re-ingest the existing HUST fixture and confirm canonical rows still land cleanly; second ingestion of the same source updates that source's row rather than failing or duplicating.
- Confirm via a synthetic two-source test that the new schema lets two distinct `source_url` values for the same logical program coexist as two canonical rows.
- Commit a one-page Q&A strategy note in `docs/superpowers/notes/2026-05-15-qa-strategy.md` that documents the V1 scope decision and the future RAG slice's touch points.

## Non-Goals

- Any RAG implementation (no embeddings, no chunking, no vector index, no `qa_agent`). The strategy note describes the future shape; it does not implement.
- Onboarding any new school. VNU-UET and NEU each have their own spec.
- Any change to the advisory graph or any agent's behavior.
- Reshaping `source_registry`, `discovered_resources`, `raw_documents`, or `extracted_facts`. They are untouched.
- Refactoring the writer beyond the `ON CONFLICT` target swap. The `SET` clause stays as-is.
- A rollback migration. If a rollback is needed, restore from a database backup; the forward path is one-way.
- Editing `docs/superpowers/specs/2026-05-13-conflict-aware-advisory-v1-design.md`. Its Slice 1 will need to be revisited at execution time; this spec documents the impact but does not modify the source.

## Migration Design

`db/migrations/010_canonical_records_per_source.sql`:

```sql
-- Drop the old uniqueness constraint that overwrote second-source rows.
-- The constraint was created by `UNIQUE(...)` inline in CREATE TABLE
-- (db/migrations/005_canonical_programs.sql), so Postgres assigned an
-- auto-generated name. We look it up by columns instead of hardcoding the
-- name, since the auto-generated name can be truncated past 63 chars.
DO $$
DECLARE
    old_constraint_name TEXT;
BEGIN
    SELECT conname INTO old_constraint_name
    FROM pg_constraint
    WHERE conrelid = 'canonical_admission_records'::regclass
      AND contype = 'u'
      AND array_length(conkey, 1) = 4
      AND (
          SELECT array_agg(attname ORDER BY attname)
          FROM pg_attribute
          WHERE attrelid = 'canonical_admission_records'::regclass
            AND attnum = ANY(conkey)
      ) = ARRAY['admission_method','admission_year','program_id','school_id'];

    IF old_constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE canonical_admission_records DROP CONSTRAINT %I',
            old_constraint_name
        );
    END IF;
END$$;

-- Add per-source uniqueness so two sources for the same logical program
-- coexist as two rows.
ALTER TABLE canonical_admission_records
    ADD CONSTRAINT canonical_admission_records_per_source_key
    UNIQUE (school_id, admission_year, program_id, admission_method, source_url);
```

### Why not also touch indexes

The existing indexes (`idx_canonical_school`, `idx_canonical_year`, `idx_canonical_program` from `005_canonical_programs.sql`) remain useful. The new uniqueness constraint creates its own backing index automatically. No additional index work is in scope.

### Migration safety

- The drop block is idempotent — the constraint lookup returns `NULL` on the second run and the `EXECUTE` is skipped. The second `ADD CONSTRAINT` will fail loudly on re-run if the new constraint already exists, which is the intended behavior (signals an operator that the migration was already applied).
- The migration is forward-only. There is no rollback migration. Rollback path is restore-from-backup.
- The migration is safe on populated databases that already have unique-per-tuple rows: every existing row has a `source_url` set (the writer populates it for every insert), so adding `source_url` to the uniqueness key cannot violate existing data.
- Database operators run the migration through whatever the project's standard migration tool is. This spec doesn't introduce one.

## Writer Change

`ingestion/storage/db_writer.py:save_canonical_records` — line 181, single-line change to the `ON CONFLICT` target:

```sql
-- Before:
ON CONFLICT (school_id, admission_year, program_id, admission_method)

-- After:
ON CONFLICT (school_id, admission_year, program_id, admission_method, source_url)
```

The `DO UPDATE SET` clause stays unchanged. After the change, the semantics become:
- **Same source, same logical program, re-ingested:** row's mutable fields refresh (quota, deadline, tuition, metadata, `normalized_at`). Existing behavior preserved.
- **Different source, same logical program:** new row inserted. Previous source's row stays put. New behavior — this is the unlock.

No other code in the writer changes. The Python function signature, the column list, the `INSERT` shape, the `SET` clause, the error handling are all identical.

## Q&A Strategy Note

Location: `docs/superpowers/notes/2026-05-15-qa-strategy.md`. Committed alongside this spec.

Outline of its content:

### Scope decision for V1

- The conflict-aware advisory V1 answers profile-driven recommendation questions ("which programs fit my profile?"). Those questions are served by structured SQL retrieval over `canonical_admission_records` — already implemented at `services/retrieval_service.py:fetch_candidates`. **The database is ready for those queries.** The conflict-aware spec adds field-level conflict resolution on top; it does not change the retrieval shape.
- The database is **not ready** for open-ended student Q&A ("what scholarships does HUST offer?", "what's the early-admission deadline at UET?", "does program X accept high-school olympiad winners?"). The answers to those questions live in the source text body, captured in `raw_documents.parsed_text` but not semantically indexed. Open-ended Q&A is **deferred to a separate post-V1 spec**.

### Why the deferral is safe

- The advisory agent and the future Q&A agent serve different intents. Routing student input to one or the other is a chat-layer concern, not a graph-layer concern. The conflict-aware advisory graph stays as-is; the Q&A agent will be a separate graph or a separate chain.
- `raw_documents.parsed_text` is already populated for every fetched source. The future RAG slice has its raw material ready — no re-fetching needed.
- The conflict-aware spec consumes `canonical_admission_records`, not raw text. Conflict resolution in V1 is field-level (quota mismatch between two sources). Narrative-passage conflicts (two source texts saying different things about scholarships) are a different problem with different resolution semantics. The V1 design does not have to cover that case.

### Future RAG slice — touch points to preserve

This is the contract that V1 must not violate, written down so future readers know which lines are load-bearing:

- **Keep `raw_documents.parsed_text` populated.** Do not drop or null it out as an "optimization." The future RAG slice reads it.
- **Keep `raw_documents.fetched_at`.** Recency signal for embedding-refresh logic.
- **Keep `raw_documents.source_id` joinable to `source_registry`.** Authority and trust signals carry into RAG ranking too.
- The future RAG slice will introduce:
  - A `document_chunks` table (id, raw_document_id, chunk_index, body_text, embedding `vector(N)`, char_start, char_end, …). New table, no existing schema disturbed.
  - A chunking + embedding stage that reads `raw_documents` and writes `document_chunks`. New pipeline stage, runs after `save_raw_document`.
  - A `qa_agent` that issues semantic retrieval queries against `document_chunks` and constructs a grounded answer. New agent, separate from `advisory_agent`.
  - A chat-layer intent classifier that routes input to either `advisory_agent` or `qa_agent`.

### What NOT to do in V1 that would close the future doors

- Don't drop `raw_documents.parsed_text` or move it to cold storage.
- Don't make `raw_documents.source_id` non-joinable to `source_registry` (e.g., by anonymizing it).
- Don't reuse the table name `document_chunks` for anything else.
- Don't bake assumptions about "the only retrieval surface is `canonical_admission_records`" into shared library code. The retrieval layer should stay a thin function call, not a configuration assumed in many places.

### Open question deferred to the future spec

- Conflict resolution semantics for narrative passages: two source texts saying contradictory things about a scholarship policy. The structured-conflict resolution layer (Evidence/Comparison/Resolution) cannot directly apply, because passage-level disagreement isn't field-level. The future Q&A spec must propose its own resolution shape (likely: surface both passages with provenance, let the LLM compose a hedged answer, never declare one passage "winning").

## Testing

### Regression: existing HUST fixture still ingests cleanly

- Reset the test database to a clean state.
- Apply migrations 001 through 010 in order.
- Run the existing HUST ingestion fixture path (whatever script the project uses today; the spec does not introduce a new one).
- Assert: canonical rows for HUST land. Same shape as before. Row count is positive.
- Re-run the same ingestion. Assert: row count unchanged (re-ingestion of the same source updates, not inserts).

### New behavior: two sources coexist

- Same clean test database with migrations applied through 010.
- Run a synthetic ingestion where the same logical `(school_id, admission_year, program_id, admission_method)` tuple is written twice with two distinct `source_url` values. Both writes go through `save_canonical_records`.
- Assert: the canonical table contains **two** rows for that tuple, one per source URL. Both rows visible to `services/retrieval_service.py:fetch_candidates`.

### What's intentionally not tested here

- The conflict detection logic that the conflict-aware spec adds. That spec owns those tests.
- Performance of canonical-row scanning at increased row counts. V1's row count target (3 schools × ~30 programs × ~2 sources = ~180 rows) is far below any scan-performance concern.
- Anything to do with the Q&A strategy note's content — it is a written design artifact, not code.

## Rollout

Single merge. The migration, the writer change, the Q&A note, and the regression tests land together. No slicing.

The merge must precede VNU-UET ingestion and NEU ingestion spec execution. Both downstream specs check at their first step that this migration is applied.

## Impact on `2026-05-13-conflict-aware-advisory-v1-design.md`

The downstream conflict-aware advisory spec's Slice 1 ("Schema fix + dataset curation (real data)") becomes partially completed by this spec. Specifically:

- The schema migration item ("Add `db/migrations/010_canonical_records_per_source.sql`…") is **done** when this spec lands. The conflict-aware implementer skips it.
- The writer change item ("Update `ingestion/storage/db_writer.py:save_canonical_records` to use the new conflict target") is **done** when this spec lands. The conflict-aware implementer skips it.
- The dataset curation item ("Pre-flight check on VNU-UET sources, source-registry entries, parser tuning if needed, ingestion of HUST + VNU-UET corpus, acceptance-criteria SQL check") is **done** when Specs B and C land. The conflict-aware implementer skips per-school work and only does the cross-school SQL acceptance check (≥3 conflict-bearing program-method tuples across the corpus) plus the dump export to `tests/e2e/fixtures/real_dataset_dump.sql`.

This spec does not edit the conflict-aware spec file. The conflict-aware spec stays as the historical design record; the implementer reads both specs and reconciles.

## Tradeoffs

### Benefits

- Unblocks every downstream spec without forcing them to each carry the same schema/writer change.
- Keeps the change surface minimal — one migration, one `ON CONFLICT` line, one note.
- The Q&A strategy note converts an ambiguous design question into a written, reviewable artifact, removing a class of "should V1 do this?" disputes during the conflict-aware spec's execution.

### Costs

- Three specs (this one + B + C) instead of one mean three review cycles instead of one. The user explicitly chose this; the tradeoff is review overhead for clearer parallelism.
- Forward-only migration with no rollback is a real risk if the new uniqueness constraint turns out to be wrong. Mitigation: the test suite exercises both regression and new behavior before merge.
- The Q&A strategy note creates expectation that RAG will eventually be built. If that work never lands, the note becomes stale. Acceptable — staleness is easier to fix than the alternative of leaving the question unanswered.

## Decision Summary

- **Phase name:** Canonical Records Per-Source Coexistence + Q&A Strategy Note (foundation for the conflict-aware advisory program).
- **Scope:** schema migration `010_canonical_records_per_source.sql`, writer `ON CONFLICT` target swap, regression and new-behavior tests, Q&A strategy note committed.
- **Reliability posture:** forward-only migration; tests gate the merge.
- **Explicitly deferred:** all RAG / Q&A implementation; school onboarding; agent changes; rollback migration.
- **Downstream impact:** VNU-UET ingestion and NEU ingestion specs depend on this. Conflict-aware advisory V1 spec's Slice 1 becomes partially completed.
