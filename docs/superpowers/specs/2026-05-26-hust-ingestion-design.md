# HUST 2026 Admission Data Ingestion

## Summary

Ingest real 2026 admission data for HUST (Đại học Bách khoa Hà Nội) through the existing ingestion pipeline (`Source Registry → Fetch → Document Router → Parser → Extractor → Normalizer → Storage`). Two distinct sources cover the same logical programs: HUST's own program listing page (`ts.hust.edu.vn/training-cate/nganh-dao-tao-dai-hoc`) and an official secondary source — either the HUST 2026 admission proposal PDF (preferred) or the HUST brochure PDF as a documented bail-out. Both land as separate canonical rows under the per-source uniqueness key from spec `2026-05-15-canonical-records-per-source-design.md`. Acceptance is at least one program-method tuple where quota differs between the two sources.

This spec is the HUST parallel of `2026-05-15-vnu-uet-ingestion-design.md`. It deliberately follows the same five-step pattern so that future schools (NEU, FTU, USTH, …) can be onboarded by copying either tree and substituting school identifiers, URLs, and parser names. This spec is pure data work plus one likely-new specialized PDF parser; no agent code, no schema change.

## Problem Statement

HUST is one of the two thesis-defense schools the conflict-aware advisory V1 spec depends on. The other is VNU-UET, ingested under spec `2026-05-15-vnu-uet-ingestion-design.md`. VNU-UET alone cannot satisfy the conflict-aware spec's Slice 1 dataset gate (≥3 conflict-bearing program-method tuples across the corpus) because after the parser correctness fix in commit `6b56301`, the VNU-UET homepage no longer emits the (semantically wrong) `dự bị` allocation rows that previously synthesized conflicts. With VNU-UET providing organic conflict only from the proposal PDF alone is impossible; the gate now requires a second school.

Today the corpus has:

- A working `hust_program_parser.py` (from the original ingestion infrastructure, commit `b9953db`).
- Zero HUST source-registry entries — commit `791310b` deleted them during repository cleanup, and the later VNU-UET seed-rewrite (`72fe1e6`) did not restore HUST.
- Zero HUST canonical records ever persisted by an end-to-end ingestion run in the repo's history.

Without HUST ingested:

- The conflict-aware advisory spec's Slice 1 acceptance check (≥3 conflict-bearing program-method tuples across the corpus) cannot pass with VNU-UET alone.
- The thesis-defense demonstration of "the system resolves a real cross-source quota conflict" lacks the second school it was designed around.
- The future Q&A slice has no HUST text in `raw_documents.parsed_text` to retrieve from.

The fix is straightforward in shape — restore HUST registry rows, find a second source, run the existing pipeline — but it carries real risk: the 2026 HUST proposal PDF may not yet be published, the program-listing parser currently emits `admission_method = None` for every card (which collapses the conflict-grouping key), and PDF table extraction quality is the same risk surface that bit VNU-UET.

## Goals

- Discover and catalog HUST's 2026 admission sources (program listing, proposal PDF, brochure PDF).
- Pass pre-flight inspection on at least one source pair: both sources reachable, both parseable in principle, ≥3 programs with diverging numeric quota, program names align unambiguously, and both sources publish the same semantic measurement (both program totals, or both method-level quotas).
- Restore HUST entries in `ingestion/registry/seeds/initial_sources.json` (lost in commit `791310b`) with appropriate `trust_level`, `parser_profile`, and `is_official` fields, alongside the existing VNU-UET rows.
- Configure parser profiles (or add a thin school-specific PDF parser if needed) so that fetch → parse → extract returns admission facts for HUST programs from both sources.
- Ensure that for every conflict-bearing program, both sources emit the same canonical `admission_method` value, so that the conflict-detection SQL groups them on the same row pair.
- Extend the normalization dictionaries (`programs.json`, `methods.json`, and `combo_method_rules.json`) with whatever HUST program names and methods aren't already covered.
- Run the full pipeline for `school_id="hust"` and persist canonical rows.
- Pass the per-school SQL acceptance check: ≥1 program-method tuple with distinct quota values across two canonical rows for the same `(school_id, admission_year, program_id, admission_method)` key.

## Non-Goals

- Any agent or graph change. The advisory agents are not touched.
- Any database schema change. The per-source uniqueness migration is owned by spec `2026-05-15-canonical-records-per-source-design.md` and is already applied.
- Re-ingesting VNU-UET. That spec is done and its findings stand; HUST work runs independently.
- NEU, FTU, or any third-school ingestion. Those follow this same template once they become priority.
- Wide parser refactoring. If a new HUST proposal-PDF parser is needed, it sits next to `vnu_uet_proposal_pdf_parser.py` as a parallel thin parser — it does not refactor shared parser code.
- Embeddings or vector indexing. Out of scope for V1 per the Q&A strategy note.
- The dataset dump export to `tests/e2e/fixtures/real_dataset_dump.sql`. That stays in the conflict-aware spec's Slice 1 because it spans all schools.
- The cross-school acceptance check (≥3 conflict-bearing tuples across the corpus). That belongs to the conflict-aware spec, not this one. This spec only commits to ≥1 conflict-bearing tuple for HUST.

## Prerequisites

Before this spec's first step:

- Spec `2026-05-15-canonical-records-per-source-design.md` is merged: the migration `010_canonical_records_per_source.sql` is applied, and `ingestion/storage/db_writer.py:save_canonical_records` uses the new `ON CONFLICT (school_id, admission_year, program_id, admission_method, source_url)` target. As of this spec, both are already in `feat/conflict-aware-slice-1` branch state.
- A working Postgres instance reachable by `ingestion/storage/db_connection.py`. The Docker-compose dev DB introduced by `e0a3ece` is the expected setup.
- Spec `2026-05-15-vnu-uet-ingestion-design.md` does not need to be merged for HUST work to start, but the VNU-UET registry rows in `initial_sources.json` must remain intact when HUST entries are appended.

## Step 1 — Source Discovery

Catalog the candidate sources before any registry edit. Inspect each manually and write findings to `docs/ingestion/hust-preflight-findings.md` (mirroring `docs/ingestion/vnu-uet-preflight-findings.md`). Deliverable fields per candidate: URL, expected `source_type`, expected `trust_level` relative to others, expected `parser_profile`, observed content type (HTML / PDF / other), and whether it's behind auth or rate limiting.

Candidate sources to evaluate:

- **HUST program listing** at `https://ts.hust.edu.vn/training-cate/nganh-dao-tao-dai-hoc`. Public HTML. `source_type="program_listing"`, `parser_profile="hust_programs"` (already exists). Confirmed reachable at the time this spec was written (HTTP 200, ~500 KB payload).
- **HUST 2026 admission proposal PDF**, URL discovered via the proposal-listing page at `https://ts.hust.edu.vn/b/de-an-tuyen-sinh`. Public PDF (verify it's text-based, not a scan, and that it covers the 2026 cycle). `source_type="admission_proposal"`, highest trust level among the candidates. **Risk:** at the time this spec was written, the listing page contained no direct PDF links and no 2026 article links — the PDF may be linked from a deeper article, may be published later in the admission cycle, or may not exist yet.
- **HUST brochure PDF** at `https://nxbbachkhoa.vn/ebook-free/12397/0/1` ("Brochure Thông tin tuyển sinh", linked from `ts.hust.edu.vn`). Bail-out secondary source if the proposal PDF cannot be found or extracted. `source_type="brochure"`, mid trust level.

Other sources (Facebook fanpages, third-party rankers, alumni-published spreadsheets, news articles) are out of scope for this spec.

## Step 2 — Pre-Flight Inspection

Before any code or registry change, the implementer manually verifies the source pair satisfies five conditions. Failure on any axis triggers a documented bail-out before proceeding.

### Pre-flight checklist

- [ ] Both sources reachable without authentication, no rate-limiting that blocks repeated fetches.
- [ ] PDF source is text-extractable, not a scanned image. Confirm by opening it in a PDF reader and selecting text from a quota table.
- [ ] At least 3 programs appear in both sources with a numeric quota that is **distinct** across the two sources for the 2026 admission year.
- [ ] Program names align unambiguously across the two sources. For each of the ≥3 conflict-bearing programs, write down the program name as it appears in each source side-by-side; the mapping must be obvious to a human, not ambiguous.
- [ ] **Both sources publish the same semantic measurement.** If the program listing's `Chỉ tiêu tuyển sinh: N` is the program total and the PDF breaks quota by admission method, that is **not** a real conflict — it's apples-to-oranges. Either both sources must report program totals, or both must report method-level quotas, or the implementer must extract the comparable subset from each.

This last check is the most important learning from the VNU-UET execution (see commit `6b56301` and the comment in `ingestion/parsers/vnu_uet_admission_parser.py:266`). Skipping it produces fabricated conflicts that the conflict-aware advisory will then dutifully "resolve" — meaningless theatre.

### Bail-outs

- **Proposal PDF not found, paywalled, or unparseable:** substitute the brochure PDF as the second source. The spec's acceptance criterion (≥1 conflict-bearing tuple) still applies. Document the substitution in the pre-flight findings file.
- **Brochure PDF also unparseable:** the second source must be a different official HUST channel. Candidates of last resort: an HTML announcement page on `ts.hust.edu.vn` that contains per-program quota numbers (e.g., a 2026 admission scheme article). Avoid third-party sources — the thesis story needs two genuinely independent **official** sources.
- **Program-name alignment is ambiguous:** swap the source pair before parser work begins. Do not try to resolve it by editing the normalization dictionary mid-flight.
- **Fewer than 3 quota-divergent programs found in pre-flight:** lower the per-school target to ≥1 conflict-bearing tuple and document the reduction. If even 1 isn't found, escalate — do not proceed with parser work.
- **Semantic-measurement mismatch (the trap from VNU-UET commit `6b56301`):** abort. Do not proceed by treating asymmetric measurements as a conflict.

The pre-flight result is committed as `docs/ingestion/hust-preflight-findings.md` (mirroring the VNU-UET findings file). It must include a "Pre-flight verdict: PROCEED / PROCEED_WITH_CAVEATS / ABORT" line before subsequent plans begin.

## Step 3 — Source-Registry Entries

After pre-flight passes, append HUST registry rows to `ingestion/registry/seeds/initial_sources.json` alongside the existing VNU-UET entries. **Append**, do not overwrite — the historical lesson from commits `791310b` (which deleted the file) and `72fe1e6` (which recreated it with VNU-UET only) is that whole-file rewrites silently drop prior schools.

Expected fields per row, matching `SourceEntry`:

- `source_id`: unique, e.g. `hust_program_listing_2026`, `hust_proposal_pdf_2026`, or `hust_brochure_pdf_2026` (whichever was selected in Step 2).
- `school_id`: `"hust"`.
- `school_name`: canonical Vietnamese name. Recommended: `"Đại học Bách khoa Hà Nội"` (matches the existing string in `ingestion/parsers/hust_program_parser.py:223`).
- `source_type`: `program_listing` / `admission_proposal` / `brochure` as appropriate.
- `root_url`: the URL recorded in pre-flight.
- `parser_profile`: `hust_programs` for source #1 (already exists); `default_pdf` or a new `hust_proposal_pdf` / `hust_brochure_pdf` for source #2 — revisit after Step 4.
- `trust_level`: proposal PDF > program listing > brochure. Concrete numeric values follow the existing convention used by VNU-UET entries — read the registry before assigning.
- `is_official`: `true` for all three categories.
- `active`: `true`.

After editing, re-seed via `python -m db.setup_db` (the seed insert is idempotent via `ON CONFLICT (source_id) DO NOTHING`).

### Acceptance for Step 3

Run `IngestionPipeline().list_schools()` and confirm HUST shows up with the expected number of active sources (≥2). Spot-check the DB with `SELECT source_id, school_id, active FROM source_registry WHERE school_id='hust';`.

## Step 4 — Parser / Profile Work

Try in this order, stopping at the first that works end-to-end:

1. **Default profiles / existing parser.** Source #1 already has `parser_profile="hust_programs"` wired to `HustProgramParser`. Run the pipeline on source #1 and confirm it produces ≥10 `ExtractedAdmissionFact` rows with non-empty `program_name` and `quota_raw`. For source #2, try `parser_profile="default_pdf"` first. If both produce usable facts, no new code is required.
2. **Profile tuning.** If the default PDF profile returns noise or misses the quota field for source #2, try tuning selectors/patterns through the existing parser configuration surface. If source #1's parser misses programs or sets `admission_method = None` in a way that breaks the conflict-grouping key (see Step 5), tweak the existing `HustProgramParser` to set a sensible default method (e.g., infer `thpt_score` when the program card lists subject combinations like A00, B00). Keep tweaks small and tested.
3. **Thin school-specific PDF parser.** Only if profile tuning isn't enough. Add `ingestion/parsers/hust_proposal_pdf_parser.py` (or `hust_brochure_pdf_parser.py`) following the shape of `ingestion/parsers/vnu_uet_proposal_pdf_parser.py`. The new parser must be registered through the existing parser dispatcher (`ingestion/parsers/parser_dispatcher.py`). It must return `List[ExtractedAdmissionFact]` so the pipeline branch in `ingestion_pipeline.py:96` picks it up without changes.

### Acceptance for Step 4

For each accepted source, running `dispatch_parser` on a freshly fetched copy returns either `ParsedContent` with non-empty `text` and recognizable quota mentions, or `List[ExtractedAdmissionFact]` directly. Spot-check at least one fact per conflict-bearing program.

### Risks within Step 4

- **PDF table extraction quality.** If the proposal/brochure PDF's quota tables don't survive `pdfplumber` extraction cleanly, no amount of profile tuning fixes it. Fall back to the bail-outs in Step 2.
- **`admission_method = None` collapses the conflict signal.** The current `HustProgramParser` emits each program card with `admission_method_raw = None` unless a detail-page sub-fetch yields a method. The conflict-detection SQL groups by `(school_id, year, program_id, admission_method)`; if source #1 emits `admission_method = NULL` and source #2 emits `'thpt_score'`, the two rows do **not** group together and Query B returns zero. Fix in Plan 03: ensure both sources emit the same canonical method value for the same logical program-method tuple, either by tuning the HUST parser to infer a default or by stripping the method discriminator on the second source.
- **HTML structure changes during the work.** HUST could update its program listing mid-spec-execution. Snapshot the raw HTML into `raw_documents` at the start of parser work and develop against the snapshot to avoid drift.

## Step 5 — Normalization / Program Mapping

The normalization stage canonicalizes program names and admission methods through dictionaries at `ingestion/normalization/dictionaries/programs.json`, `methods.json`, and `combo_method_rules.json`. A handful of HUST-mentioning entries already exist (from commit `b9953db`); inventory what's there before extending.

For every conflict-bearing program discovered in Step 1, ensure `programs.json` maps each program-name surface form (Vietnamese + English variants, as published by source #1 and source #2) to the same canonical `program_id` and `program_name_canonical`. If method names differ across sources, add `methods.json` entries so both surface forms resolve to the same canonical `admission_method`.

### Acceptance for Step 5

Run normalization on the Step-4 extracted facts. For every conflict-bearing program-method tuple, the normalized record has:

- `program_id` non-null, identical across both sources.
- `program_name_canonical` non-null, identical across both sources.
- `admission_method` non-null and identical across both sources (or both NULL, which the conflict-detection SQL also groups together).

If `program_id` differs between sources for what is supposed to be the same logical program, the program-name mapping is broken — fix the dictionary before proceeding. If `admission_method` differs, fix per the same logic.

## Step 6 — Canonical Record Writing

Run `IngestionPipeline().run_for_school("hust")` and persist the output. The writer (per spec `2026-05-15-canonical-records-per-source-design.md`) inserts one row per source for each logical program.

Note: as of this spec, `ingestion_pipeline.py` returns normalized records but does not itself call `save_canonical_records`. The execution path mirrors `db/reimport.py` — load pipeline output and explicitly call the writer. The HUST plan's pipeline-run script will be a small wrapper that does both, structured the same as the VNU-UET execution path.

### Acceptance for Step 6

Spot-check via SQL:

```sql
SELECT school_id, program_name_canonical, admission_method, source_url, quota
FROM canonical_admission_records
WHERE school_id = 'hust'
  AND admission_year = 2026
ORDER BY program_name_canonical, admission_method, source_url;
```

Rows are present, every row has a `source_url`, every row has a `quota` JSONB blob populated, the `program_name_canonical` column groups rows correctly across sources.

## Step 7 — Acceptance SQL Checks

Two queries, both must pass.

**Query A — row count for HUST is positive:**

```sql
SELECT COUNT(*) AS row_count
FROM canonical_admission_records
WHERE school_id = 'hust'
  AND admission_year = 2026;
```

Expected: > 0. Target: ≥ 10 rows.

**Query B — at least one conflict-bearing tuple for HUST:**

```sql
SELECT school_id, admission_year, program_id, admission_method,
       COUNT(DISTINCT quota::text) AS distinct_quota_values
FROM canonical_admission_records
WHERE school_id = 'hust'
  AND admission_year = 2026
  AND quota IS NOT NULL
GROUP BY school_id, admission_year, program_id, admission_method
HAVING COUNT(DISTINCT quota::text) > 1;
```

Expected: ≥ 1 row returned. Each returned row corresponds to one program-method tuple where at least two canonical rows disagree on quota — exactly the signal the conflict-aware spec needs.

Both queries are part of the spec's acceptance gate. If either fails, the spec is not done.

### Manual sanity check after the SQL passes

Read the actual quota JSONB values for at least one conflict-bearing tuple. Confirm the numbers are real (not a normalization artifact, not a semantic-measurement mismatch slipped past Step 2). If the conflict turns out to be a normalization difference rather than a genuine source disagreement, fix the quota normalizer rather than declaring victory.

## Testing

This spec is data work plus possibly one new specialized PDF parser; the primary assertions are SQL acceptance queries on a real database.

- If `hust_proposal_pdf_parser.py` (or `hust_brochure_pdf_parser.py`) is created, add a small unit test mirroring `tests/ingestion/test_vnu_uet_proposal_pdf_parser.py` against a captured PDF fixture saved under `ingestion/parsers/_fixtures/`. Otherwise no new unit tests required.
- The existing pipeline's unit tests (`tests/ingestion/...`) must continue to pass; running them is a sanity gate that no shared code broke during parser-profile or normalization edits.
- The VNU-UET pipeline-run acceptance must continue to pass after HUST changes land — re-run `python -m ingestion.main --school vnu_uet` and confirm Query B for `school_id='vnu_uet'` still returns the previously-recorded result. Shared-code edits in Step 4/5 are the likeliest regression source.

## Rollout

Execute steps 1–7 in order via the five implementation plans under `docs/superpowers/plans/2026-05-26-hust-crawl/`. Each step has its own acceptance gate; do not start the next step until the previous one's gate is green.

The work merges in logical chunks (same as VNU-UET):

1. **Source-registry + dictionary edits** (Steps 3 + 5) land as one PR if dictionary entries are pure additions.
2. **Parser-profile or new-parser code** (Step 4) lands as its own PR, since it's the only code change of substance.
3. **Acceptance SQL findings** (Steps 6 + 7) are documented in `docs/ingestion/hust-preflight-findings.md` under an "Ingestion acceptance" appendix.

If pre-flight (Step 2) fails irrecoverably (bail-outs exhausted), the spec is paused and escalated rather than merged with partial work.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| 2026 HUST proposal PDF not yet published or not discoverable | Step 2 bail-out: brochure PDF as second source. |
| PDF table extraction quality poor for whichever PDF is chosen | Step 4 escalates to a thin school-specific PDF parser mirroring `vnu_uet_proposal_pdf_parser.py`. |
| `admission_method = None` from `HustProgramParser` collapses conflict-grouping | Step 4 tier-2 tuning ensures both sources resolve to the same canonical method (either default-infer or strip). Step 5 invariant enforces this. |
| Semantic-measurement mismatch (program total vs method-level), the VNU-UET trap | Step 2 has a dedicated check for this. Abort if the two sources don't publish comparable measurements. |
| Fewer than 3 quota-divergent programs in 2026 | Reduce the per-school target to ≥1 conflict-bearing tuple (spec acceptance is ≥1, not ≥3 — the ≥3 target is cross-school). |
| Program-name alignment ambiguous between program listing and proposal PDF | Step 2 explicitly checks. Swap source pair (use brochure) before parser work. |
| HUST updates its admission pages mid-execution | Snapshot raw HTML/PDF into `raw_documents` at the start of parser work. Develop against the snapshot. |
| Whole-file rewrite of `initial_sources.json` drops VNU-UET rows (historical lesson) | Step 3 explicitly says append, not overwrite; spec's prerequisites note the cautionary commit history. |
| Spec A migration not yet applied | Step 1 of execution checks `\d canonical_admission_records` in psql; halt if the `source_url` column isn't in the unique key. |

## Tradeoffs

### Benefits

- Operationalizes the second of the two thesis-defense schools on real 2026 data.
- Independent of NEU / FTU ingestion; can run in parallel with any future school's work.
- Builds zero new shared infrastructure; reuses every layer of the existing pipeline. The likely new code is one specialized PDF parser, modeled on VNU-UET's.
- Establishes the per-school crawl playbook as a parallel pair (VNU-UET + HUST). The next school onboarded follows the same five-plan structure by copying either tree and substituting names.
- The acceptance check is two SQL queries — easy to verify, hard to fake.

### Costs

- Real-data ingestion remains the slowest, riskiest kind of pipeline work. Most of the schedule risk for the conflict-aware advisory program lives here and in the VNU-UET counterpart.
- The spec carries some "judgment call" surface in Step 4 (when to graduate from profile tuning to a school-specific parser). Implementer needs taste; no test guards against premature parser-creation.
- Snapshotting raw HTML/PDF at parser-work start adds discipline overhead and isn't enforced by any automation.
- The `admission_method = None` issue in the existing HUST parser is a known sharp edge that didn't exist for VNU-UET. The spec carries the responsibility to fix it during Step 4, which is light parser work but easy to forget.

## Decision Summary

- **Phase name:** HUST 2026 admission data ingestion.
- **Scope:** source discovery → pre-flight → registry entries → parser/profile config (or thin PDF parser) → normalization dictionary entries → canonical records → SQL acceptance.
- **Reliability posture:** real-data work; acceptance gated by SQL queries against the actual canonical-records state. Bail-outs documented for each major risk surface, including the VNU-UET semantic-measurement trap.
- **Explicitly deferred:** agent changes, schema changes, NEU/FTU work, dataset dump export, cross-school acceptance.
- **Prerequisite:** Spec `2026-05-15-canonical-records-per-source-design.md` merged (already applied on `feat/conflict-aware-slice-1`).
- **Downstream consumer:** the conflict-aware advisory V1 spec's Slice 1 dataset gate (≥3 conflict-bearing tuples across the corpus, achieved by VNU-UET + HUST together).
- **Sibling spec:** `2026-05-15-vnu-uet-ingestion-design.md` is the structural twin; this spec deliberately mirrors its section layout, step numbering, and acceptance-gate wording so the pair functions as a per-school crawl playbook.
