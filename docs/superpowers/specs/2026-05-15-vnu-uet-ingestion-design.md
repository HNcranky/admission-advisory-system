# VNU-UET 2026 Admission Data Ingestion

## Summary

Ingest real 2026 admission data for VNU-UET (Đại học Công nghệ, ĐHQGHN) through the existing ingestion pipeline (`Source Registry → Fetch → Document Router → Parser → Extractor → Normalizer → Storage`). Two distinct sources cover the same logical programs: VNU-UET's own admission homepage (`uet.vnu.edu.vn`) and the ĐHQGHN-wide admission proposal published as a PDF. Both land as separate canonical rows under the per-source uniqueness key from spec `2026-05-15-canonical-records-per-source-design.md`. Acceptance is at least one program-method tuple where quota differs between the two sources.

This is pure data work. No agent code, no schema change. The only code touched is parser configuration / a thin school-specific parser if pre-flight requires it, plus normalization dictionary entries.

## Problem Statement

VNU-UET is one of the two thesis-defense schools the conflict-aware advisory V1 spec depends on. The other is HUST, already partially ingested via the existing `hust_program_parser.py` and one program fixture.

Today the corpus has no VNU-UET data and no cross-source conflict on real data. Without VNU-UET ingested:

- The conflict-aware advisory spec's Slice 1 acceptance check (≥3 conflict-bearing program-method tuples across the corpus) cannot pass.
- The thesis-defense demonstration of "the system resolves a real cross-source quota conflict" has no real conflict to resolve.
- The future Q&A slice has no VNU-UET text in `raw_documents.parsed_text` to retrieve from.

The fix is straightforward in shape — run the existing pipeline on VNU-UET's sources — but it carries real risk: parser quality on the ĐHQGHN proposal PDF, program-name alignment between two sources that don't use identical names, and the possibility that the two sources don't actually conflict on quota in 2026.

## Goals

- Discover and catalog VNU-UET's 2026 admission sources (admission homepage, program pages, ĐHQGHN proposal PDF).
- Pass pre-flight inspection on at least one source pair: both sources reachable, both parseable in principle, ≥3 programs with diverging numeric quota, program names align unambiguously.
- Add source-registry entries for each accepted source with appropriate `trust_level`, `parser_profile`, and `is_official` fields.
- Configure parser profiles (or add a thin school-specific parser if needed) so that fetch → parse → extract returns admission facts for VNU-UET programs.
- Extend the normalization dictionaries (`programs.json` and any combo/method rule files) with the VNU-UET program names and methods needed for canonicalization.
- Run the full pipeline for `school_id="vnu_uet"` and write canonical rows.
- Pass the per-school SQL acceptance check: ≥1 program-method tuple with distinct quota values across two canonical rows for the same `(school_id, admission_year, program_id, admission_method)` key.

## Non-Goals

- Any agent or graph change. The advisory agents are not touched.
- Any database schema change. The per-source uniqueness migration is owned by spec `2026-05-15-canonical-records-per-source-design.md`.
- NEU ingestion. That is its own spec (`2026-05-15-neu-ingestion-design.md`) and can run in parallel with this one.
- Wide parser refactoring. New code, if any, sits next to `hust_program_parser.py` as a parallel thin parser — it does not refactor shared parser code.
- Embeddings or vector indexing. Out of scope for V1 per the Q&A strategy note.
- The dataset dump export to `tests/e2e/fixtures/real_dataset_dump.sql`. That stays in the conflict-aware spec's Slice 1 because it spans all schools.
- The cross-school acceptance check (≥3 conflict-bearing tuples across the corpus). That belongs to the conflict-aware spec, not this one. This spec only commits to ≥1 conflict-bearing tuple for VNU-UET.

## Prerequisites

Before this spec's first step:

- Spec `2026-05-15-canonical-records-per-source-design.md` is merged: the migration `010_canonical_records_per_source.sql` is applied, and `ingestion/storage/db_writer.py:save_canonical_records` uses the new `ON CONFLICT` target. Without this, the second source's row silently overwrites the first, killing the conflict signal this spec is meant to produce.
- A working Postgres instance reachable by `ingestion/storage/db_connection.py`. The existing development setup is sufficient.

## Step 1 — Source Discovery

Catalog the candidate sources before any registry edit. Inspect each manually and write down what you find. Deliverable: a short document (can live inline in this spec's PR description) listing each candidate URL with these fields: URL, expected `source_type`, expected `trust_level` relative to others, expected `parser_profile`, observed content type (HTML / PDF / other), and whether it's behind auth or rate limiting.

Candidate sources to evaluate:

- **UET admission homepage** (`uet.vnu.edu.vn`-rooted). Public HTML. Likely `source_type="admission_homepage"`, mid trust level.
- **UET per-program pages** linked from the admission homepage. Public HTML. Likely `source_type="program_page"`, lower trust level than the homepage.
- **ĐHQGHN admission proposal PDF.** Published annually by ĐHQGHN covering all member units including UET. Public PDF (verify it's text-based, not a scan). Likely `source_type="admission_proposal"`, highest trust level among the candidates.

Other sources (Facebook fanpage, alumni-published spreadsheets, news articles) are out of scope for this spec.

## Step 2 — Pre-Flight Inspection

Before any code or registry change, the implementer manually verifies the source pair satisfies four conditions. Failure on any axis triggers a documented bail-out before proceeding.

### Pre-flight checklist

- [ ] Both sources reachable without authentication, no rate-limiting that blocks repeated fetches.
- [ ] PDF source is text-extractable, not a scanned image. Confirm by opening it in a PDF reader and selecting text from a quota table.
- [ ] At least 3 programs appear in both sources with a numeric quota that is **distinct** across the two sources for the 2026 admission year.
- [ ] Program names align unambiguously across the two sources. For each of the ≥3 conflict-bearing programs, write down the program name as it appears in each source side-by-side; the mapping must be obvious to a human, not ambiguous.

### Bail-outs

- **PDF table extraction looks poor:** abandon the ĐHQGHN proposal PDF for VNU-UET. Substitute the second source with another HTML form of the same authority (e.g., an HTML version of the ĐHQGHN admission announcement, if one exists). The spec's acceptance criterion (≥1 conflict-bearing tuple) still applies.
- **Program-name alignment is ambiguous:** swap the source pair before parser work begins. Don't try to resolve it by editing the normalization dictionary mid-flight.
- **Fewer than 3 quota-divergent programs found in pre-flight:** lower the per-school target to ≥1 conflict-bearing tuple and document the reduction. If even 1 isn't found, escalate — do not proceed with parser work.
- **PDF is auth-walled or paywalled:** find a different official secondary source for VNU-UET. The thesis story needs two genuinely independent official sources; if a substitute isn't available, escalate.

The pre-flight result is committed as a short markdown note alongside the PR (or in this spec under a "Pre-flight findings" appendix once executed).

## Step 3 — Source-Registry Entries

After pre-flight passes, add registry rows for each accepted source. The registry is read by `ingestion/registry/source_registry.py`; entries live in whatever seed file the registry currently loads from (typically `ingestion/registry/seeds/initial_sources.json` if present, or whatever the project's current seed path is — confirm by reading `SourceRegistry.__init__` before editing).

Expected fields per row, matching `SourceEntry`:

- `source_id`: unique, e.g. `vnu_uet_homepage_2026`, `vnu_uet_program_<slug>_2026`, `vnuhn_proposal_2026`.
- `school_id`: `"vnu_uet"`.
- `school_name`: canonical Vietnamese name. Recommended: `"Trường Đại học Công nghệ - ĐHQGHN"`.
- `source_type`: `admission_homepage` / `program_page` / `admission_proposal` as appropriate.
- `root_url`: the URL to fetch.
- `parser_profile`: `default_html` or `default_pdf` initially; revisit after Step 4.
- `trust_level`: `proposal PDF > admission homepage > program page`. Concrete numeric values follow the existing convention used by HUST entries — read the registry before assigning.
- `is_official`: `true` for all three categories.
- `active`: `true`.

### Acceptance for Step 3

Run `IngestionPipeline.list_schools()` (or the equivalent registry inspection path) and confirm VNU-UET shows up with the expected number of active sources.

## Step 4 — Parser / Profile Work

Try in this order, stopping at the first that works end-to-end:

1. **Default profiles only.** Run the pipeline with `parser_profile="default_html"` on UET HTML sources and `parser_profile="default_pdf"` on the ĐHQGHN PDF. If extraction returns usable fact rows (program name, quota, method) for the conflict-bearing programs, no parser code change is needed. This is the desired outcome.
2. **Profile tuning.** If the default profiles return mostly noise or miss the quota field, define a school-specific profile entry (e.g., `parser_profile="vnu_uet_html"`) with tuned selectors / patterns. The profile-tuning surface is the existing parser configuration; no new Python file required.
3. **Thin school-specific parser.** Only if profile tuning isn't enough. Add `ingestion/parsers/vnu_uet_program_parser.py` following the shape of `hust_program_parser.py`. The new parser must be a plugin registered through the existing parser dispatcher (`ingestion/parsers/parser_dispatcher.py`). It must return `List[ExtractedAdmissionFact]` so the pipeline branch in `ingestion_pipeline.py:96` picks it up without changes.

### Acceptance for Step 4

For each accepted source, running `dispatch_parser` on a freshly fetched copy of the source returns either `ParsedContent` with non-empty `text` and recognizable quota mentions, or `List[ExtractedAdmissionFact]` directly. Spot-check at least one fact per conflict-bearing program.

### Risks within Step 4

- **PDF table extraction quality.** If `pdf_parser.py` cannot reconstruct rows from the proposal PDF's quota tables, no amount of profile tuning fixes it. Fall back to the bail-out from Step 2.
- **HTML structure changes during the work.** UET could update its admission pages mid-spec-execution. Snapshot the raw HTML into `raw_documents` at the start of parser work and develop against the snapshot to avoid drift.

## Step 5 — Normalization / Program Mapping

The normalization stage canonicalizes program names and admission methods through dictionaries. Edits land in `ingestion/normalization/dictionaries/programs.json` and any combo/method rule files the codebase references (`combo_method_rules.json` is mentioned in `ingestion_pipeline.py`'s docstring — verify exact filename by reading the normalizer at execution time).

Add 3-5 entries to `programs.json` per the canonical program list VNU-UET publishes for 2026 (e.g., Computer Science, Computer Engineering, AI, Information Technology, Robotics & AI). Each entry maps surface forms (Vietnamese + English variants) to the canonical `program_id` and `program_name_canonical`.

If a method appears that isn't already in the combo/method dictionary, add it. Common candidates: direct admission for olympiad winners (`xét tuyển thẳng`), priority admission (`xét tuyển ưu tiên`), THPT score combination (`xét tuyển dựa trên điểm thi THPT`), competence assessment (`đánh giá năng lực`).

### Acceptance for Step 5

Run normalization on the Step-4 extracted facts. For every conflict-bearing program, the normalized record has:

- `program_id` non-null
- `program_name_canonical` non-null and matches across both sources (this is the key invariant — without it, the conflict signal won't land on the same canonical row pair)
- `admission_method` non-null

If `program_id` differs between sources for what is supposed to be the same logical program, the program-name mapping is broken — fix the dictionary before proceeding.

## Step 6 — Canonical Record Writing

Run `IngestionPipeline().run_for_school("vnu_uet")` and let it persist. The writer (post-spec-A) inserts one row per source for each logical program.

### Acceptance for Step 6

Spot-check via SQL:

```sql
SELECT school_id, program_name_canonical, admission_method, source_url, quota
FROM canonical_admission_records
WHERE school_id = 'vnu_uet'
  AND admission_year = 2026
ORDER BY program_name_canonical, admission_method, source_url;
```

Rows are present, every row has a `source_url`, every row has a `quota` JSONB blob populated, the `program_name_canonical` column groups rows correctly across sources.

## Step 7 — Acceptance SQL Checks

Two queries, both must pass.

**Query A — row count for VNU-UET is positive:**

```sql
SELECT COUNT(*) AS row_count
FROM canonical_admission_records
WHERE school_id = 'vnu_uet'
  AND admission_year = 2026;
```

Expected: > 0. A reasonable bar: ≥ 10 rows (3+ programs × 2 sources × at least 2 methods average).

**Query B — at least one conflict-bearing tuple for VNU-UET:**

```sql
SELECT school_id, admission_year, program_id, admission_method, COUNT(DISTINCT quota) AS distinct_quota_values
FROM canonical_admission_records
WHERE school_id = 'vnu_uet'
  AND admission_year = 2026
  AND quota IS NOT NULL
GROUP BY school_id, admission_year, program_id, admission_method
HAVING COUNT(DISTINCT quota) > 1;
```

Expected: ≥ 1 row returned. Each returned row corresponds to one program-method tuple where at least two canonical rows disagree on quota — exactly the signal the conflict-aware spec needs.

Both queries are part of the spec's acceptance gate. If either fails, the spec is not done.

### Manual sanity check after the SQL passes

Read the actual quota JSONB values for at least one conflict-bearing tuple. Confirm the numbers are real (not a normalization artifact like one source reporting `120` and the other reporting `{"count": 120, "unit": "students"}`). If the conflict turns out to be a normalization difference rather than a genuine source disagreement, fix the quota normalizer rather than declaring victory.

## Testing

This spec is data work; the assertions are SQL acceptance queries on a real database, not unit tests.

- No new unit tests required.
- The existing pipeline's unit tests (`tests/ingestion/...` if present) must continue to pass; running them is a sanity gate that no shared code broke during parser-profile or normalization edits.
- The HUST fixture ingestion (from spec A's regression test) must still pass — re-run it after VNU-UET work to confirm no shared-code regression.

## Rollout

Execute steps 1–7 in order. Each step has its own acceptance gate; do not start the next step until the previous one's gate is green.

The work merges in logical chunks:

1. **Source-registry + dictionary edits** (Steps 3 + 5) can land as one PR, since they're pure configuration with no parser dependency.
2. **Parser-profile or new-parser code** (Step 4) lands as its own PR, since it's the only code change of substance.
3. **Acceptance SQL findings** (Steps 6 + 7) are documented in this spec's "Findings" appendix or in the merging PR's description. No new code, no merge required.

If pre-flight (Step 2) fails irrecoverably (bail-outs exhausted), the spec is paused and escalated rather than merged with partial work.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| ĐHQGHN proposal PDF has poor table extraction quality | Switch the second source to an HTML form per Step 2 bail-out. |
| Fewer than 3 quota-divergent programs in 2026 | Reduce the per-school target to ≥1 conflict-bearing tuple (spec acceptance is ≥1, not ≥3 — the ≥3 target is cross-school and lives in the conflict-aware spec). |
| Program-name alignment ambiguous between UET site and ĐHQGHN proposal | Step 2 explicitly checks. Swap source pair before parser work. |
| UET updates its admission pages mid-execution | Snapshot raw HTML into `raw_documents` at start of parser work. Develop against the snapshot. |
| Normalization mismatch makes the conflict signal invisible | Step 5's invariant (`program_name_canonical` matches across sources) catches this. Step 7's manual sanity check is a second line of defense. |
| Spec A migration not yet applied | Step 1 of execution checks `\d canonical_admission_records` in psql to confirm the new uniqueness constraint exists. If not, halt and apply Spec A first. |

## Tradeoffs

### Benefits

- Operationalizes one of the two thesis-defense schools on real 2026 data.
- Independent of NEU ingestion; can run in parallel.
- Builds zero new shared infrastructure; reuses every layer of the existing pipeline.
- The acceptance check is one SQL query — easy to verify, hard to fake.

### Costs

- Real-data ingestion is the slowest, riskiest kind of work in the pipeline. Most of the schedule risk for the conflict-aware advisory program lives here and in the parallel NEU spec.
- The spec carries some "judgment call" surface in Step 4 (when to graduate from profile tuning to a school-specific parser). Implementer needs taste; no test guards against premature parser-creation.
- Snapshotting raw HTML at parser-work start adds discipline overhead and isn't enforced by any automation.

## Decision Summary

- **Phase name:** VNU-UET 2026 admission data ingestion.
- **Scope:** source discovery → pre-flight → registry entries → parser/profile config (or thin parser) → normalization dictionary entries → canonical records → SQL acceptance.
- **Reliability posture:** real-data work; acceptance gated by SQL queries against the actual canonical-records state. Bail-outs documented for each major risk surface.
- **Explicitly deferred:** agent changes, schema changes, NEU work, dataset dump export, cross-school acceptance.
- **Prerequisite:** Spec `2026-05-15-canonical-records-per-source-design.md` merged.
- **Downstream consumer:** the conflict-aware advisory V1 spec's Slice 1 dataset gate.
