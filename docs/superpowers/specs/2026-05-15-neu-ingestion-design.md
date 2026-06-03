# NEU 2026 Admission Data Ingestion

## Summary

Ingest real 2026 admission data for NEU (Đại học Kinh tế Quốc dân) through the existing ingestion pipeline (`Source Registry → Fetch → Document Router → Parser → Extractor → Normalizer → Storage`). Two distinct sources cover the same logical programs: NEU's admission homepage rooted at `neu.edu.vn` and an official 2026 admission announcement document published by NEU (proposal PDF or board resolution, whichever is publicly available). Both land as separate canonical rows under the per-source uniqueness key from spec `2026-05-15-canonical-records-per-source-design.md`. Acceptance is at least one program-method tuple where quota differs between the two sources.

This is pure data work. No agent code, no schema change. The only code touched is parser configuration / a thin school-specific parser if pre-flight requires it, plus normalization dictionary entries.

This spec is independent of `2026-05-15-vnu-uet-ingestion-design.md` and can run in parallel. Both depend on the canonical-records-per-source foundation spec.

## Problem Statement

NEU is the third thesis-defense school. The conflict-aware advisory V1 spec's Slice 1 originally proposed only HUST + VNU-UET, with NEU listed as a bail-out option. Pre-baking NEU as a fully-onboarded third school provides three benefits over leaving it as a contingency:

- The cross-school acceptance criterion (≥3 conflict-bearing tuples) becomes more robust: a single school's pre-flight failure no longer puts the corpus below the bar.
- The architectural claim "the system generalizes across schools" gets a third data point instead of two.
- If VNU-UET pre-flight fails, the conflict-aware spec can proceed on HUST + NEU without scrambling for a replacement mid-execution.

Today the corpus has no NEU data. Pre-flight outcomes are unknown — NEU's published admission sources may or may not exhibit cross-source quota disagreement on 2026 programs. This spec inherits the same risk surface as the VNU-UET spec.

## Goals

- Discover and catalog NEU's 2026 admission sources (admission homepage, program pages, official announcement document).
- Pass pre-flight inspection on at least one source pair: both sources reachable, both parseable in principle, ≥3 programs with diverging numeric quota, program names align unambiguously.
- Add source-registry entries for each accepted source with appropriate `trust_level`, `parser_profile`, and `is_official` fields.
- Configure parser profiles (or add a thin school-specific parser if needed) so that fetch → parse → extract returns admission facts for NEU programs.
- Extend the normalization dictionaries with NEU's program names and admission methods.
- Run the full pipeline for `school_id="neu"` and write canonical rows.
- Pass the per-school SQL acceptance check: ≥1 program-method tuple with distinct quota values across two canonical rows for the same `(school_id, admission_year, program_id, admission_method)` key.

## Non-Goals

- Any agent or graph change.
- Any database schema change.
- VNU-UET ingestion. Owned by `2026-05-15-vnu-uet-ingestion-design.md`.
- Refactoring shared parser code. New code, if any, sits alongside `hust_program_parser.py` as a parallel thin parser.
- Embeddings or vector indexing. Out of scope per the Q&A strategy note.
- The dataset dump export to `tests/e2e/fixtures/real_dataset_dump.sql`. Stays in the conflict-aware spec's Slice 1.
- The cross-school acceptance check (≥3 conflict-bearing tuples across the corpus). This spec only commits to ≥1 conflict-bearing tuple for NEU.
- Other NEU programs beyond the ones needed to clear the acceptance gate. Scale-up is a later phase.

## Prerequisites

- Spec `2026-05-15-canonical-records-per-source-design.md` is merged: migration `010_canonical_records_per_source.sql` applied, `ingestion/storage/db_writer.py:save_canonical_records` uses the new `ON CONFLICT` target.
- A working Postgres instance reachable by `ingestion/storage/db_connection.py`.

## Step 1 — Source Discovery

Catalog the candidate sources before any registry edit. Inspect each manually and write down what you find. Deliverable: a short document listing each candidate URL with these fields: URL, expected `source_type`, expected `trust_level` relative to others, expected `parser_profile`, observed content type (HTML / PDF / other), and whether it's behind auth or rate limiting.

Candidate sources to evaluate:

- **NEU admission homepage** (`tuyensinh.neu.edu.vn` or the `neu.edu.vn`-rooted admission section, whichever is canonical for 2026). Public HTML. Likely `source_type="admission_homepage"`, mid-to-high trust level for an official school site.
- **NEU per-program pages** linked from the admission homepage. Public HTML. Likely `source_type="program_page"`, lower trust level than the homepage.
- **NEU 2026 admission announcement / proposal document.** Form depends on what NEU publishes — typically a board resolution PDF (`đề án tuyển sinh` or similar). Public PDF (verify it's text-based, not a scan). Likely `source_type="admission_proposal"`, highest trust level among the candidates.

Optional fallback sources, only if pre-flight on the primary pair fails:

- **MOET-aggregated 2026 admission data** for NEU, if MOET publishes school-by-school data publicly. Trust level high but content scope narrower.
- **Press release HTML** from NEU's news section announcing 2026 quota numbers. Trust level lower (news context, may summarize rather than restate). Use only if no proposal PDF is available.

Facebook fanpage, alumni-published spreadsheets, third-party tuition-comparison sites are out of scope.

## Step 2 — Pre-Flight Inspection

Manual verification before any code or registry change. Bail-outs documented for each failure mode.

### Pre-flight checklist

- [ ] Both sources reachable without authentication, no rate-limiting that blocks repeated fetches.
- [ ] PDF source is text-extractable, not a scanned image. Confirm by opening it in a PDF reader and selecting text from a quota table.
- [ ] At least 3 NEU programs appear in both sources with numeric quota values that are **distinct** across the two sources for 2026.
- [ ] Program names align unambiguously across the two sources. For each conflict-bearing program, write down the name as it appears in each source side-by-side; the mapping must be obvious to a human.

### Bail-outs

- **NEU's proposal PDF is a scanned image or has poor table structure:** substitute with another HTML source from the discovery list (MOET aggregate, NEU news section), preserving authority. The ≥1 conflict-bearing tuple acceptance still applies.
- **Program-name alignment ambiguous:** swap the source pair before parser work begins.
- **Fewer than 3 quota-divergent programs found in pre-flight:** keep the spec's ≥1 target. If even 1 isn't found, escalate — do not proceed with parser work.
- **Both NEU sources actually agree on all quota numbers in 2026:** this is the genuine bad case. Escalate. Options: (a) consider an additional NEU source if one exists with different numbers, (b) accept NEU as a non-conflict-bearing school in the corpus (it still demonstrates pipeline coverage even without a conflict), or (c) replace NEU with FTU and re-run this spec. Decision is escalated to the project owner.
- **NEU sources require authentication:** find a different public source pair. Authentication-walled data does not meet the thesis evidence bar.

Pre-flight findings committed as a short markdown note alongside the PR.

## Step 3 — Source-Registry Entries

After pre-flight passes, add registry rows for each accepted source. Same expected fields as the VNU-UET spec, with NEU values:

- `source_id`: e.g. `neu_admission_homepage_2026`, `neu_program_<slug>_2026`, `neu_proposal_2026`.
- `school_id`: `"neu"`.
- `school_name`: canonical Vietnamese name. Recommended: `"Trường Đại học Kinh tế Quốc dân"`.
- `source_type`: `admission_homepage` / `program_page` / `admission_proposal` as appropriate.
- `root_url`: the URL to fetch.
- `parser_profile`: `default_html` or `default_pdf` initially; revisit after Step 4.
- `trust_level`: `proposal PDF > admission homepage > program page`. Use the same numeric values as VNU-UET for parity (read existing HUST and VNU-UET entries at execution time).
- `is_official`: `true` for all three categories.
- `active`: `true`.

### Acceptance for Step 3

Run `IngestionPipeline.list_schools()` and confirm NEU shows up with the expected number of active sources.

## Step 4 — Parser / Profile Work

Same staircase as the VNU-UET spec, in order:

1. **Default profiles only.** `parser_profile="default_html"` on NEU HTML sources, `parser_profile="default_pdf"` on the NEU proposal PDF. If extraction returns usable fact rows for the conflict-bearing programs, stop here.
2. **Profile tuning.** Define `parser_profile="neu_html"` with tuned selectors / patterns if defaults miss the quota field. Configuration only, no new parser file.
3. **Thin school-specific parser.** Only if profile tuning isn't enough. Add `ingestion/parsers/neu_program_parser.py` following the shape of `hust_program_parser.py`. Register through the parser dispatcher. Return `List[ExtractedAdmissionFact]`.

### Acceptance for Step 4

For each accepted source, running `dispatch_parser` on a freshly fetched copy returns either `ParsedContent` with non-empty `text` and recognizable quota mentions, or `List[ExtractedAdmissionFact]` directly. Spot-check at least one fact per conflict-bearing program.

### Risks within Step 4

- **NEU's HTML may use heavy JavaScript rendering for program pages.** If the HTTP fetcher returns markup without the quota tables filled in, the default HTML parser will produce empty results. Confirm during Step 1 inspection whether quota appears in the initial HTTP response; if not, escalate before committing parser time.
- **PDF table extraction quality.** Same risk as VNU-UET. Same bail-out — fall back to the secondary HTML source.

## Step 5 — Normalization / Program Mapping

Add 3-5 entries to `programs.json` covering the NEU programs in the conflict-bearing set. NEU is an economics-and-business school, so expected programs include: Tài chính - Ngân hàng (Finance & Banking), Kế toán (Accounting), Kinh doanh quốc tế (International Business), Marketing, Khoa học máy tính / Hệ thống thông tin quản lý (Computer Science / Management Information Systems), Logistics và Quản lý chuỗi cung ứng (Logistics & Supply Chain Management).

If NEU uses methods not already in the combo/method dictionary, add them. Common candidates: combined admission (`xét tuyển kết hợp`), priority by IELTS/SAT (`xét tuyển ưu tiên IELTS/SAT`), THPT score combination, competence assessment.

### Acceptance for Step 5

Same invariant as VNU-UET: every conflict-bearing program's normalized record has non-null `program_id`, non-null `program_name_canonical`, and `program_name_canonical` matches across both sources of NEU. Without this, the conflict signal won't land on the same canonical row pair.

## Step 6 — Canonical Record Writing

Run `IngestionPipeline().run_for_school("neu")` and let it persist.

### Acceptance for Step 6

Spot-check via SQL:

```sql
SELECT school_id, program_name_canonical, admission_method, source_url, quota
FROM canonical_admission_records
WHERE school_id = 'neu'
  AND admission_year = 2026
ORDER BY program_name_canonical, admission_method, source_url;
```

Rows present, every row has a `source_url`, every row has a `quota` JSONB blob populated, the `program_name_canonical` column groups rows correctly across sources.

## Step 7 — Acceptance SQL Checks

Two queries, both must pass.

**Query A — row count for NEU is positive:**

```sql
SELECT COUNT(*) AS row_count
FROM canonical_admission_records
WHERE school_id = 'neu'
  AND admission_year = 2026;
```

Expected: > 0. Reasonable bar: ≥ 10 rows.

**Query B — at least one conflict-bearing tuple for NEU:**

```sql
SELECT school_id, admission_year, program_id, admission_method, COUNT(DISTINCT quota) AS distinct_quota_values
FROM canonical_admission_records
WHERE school_id = 'neu'
  AND admission_year = 2026
  AND quota IS NOT NULL
GROUP BY school_id, admission_year, program_id, admission_method
HAVING COUNT(DISTINCT quota) > 1;
```

Expected: ≥ 1 row returned.

### Manual sanity check after the SQL passes

Read the actual quota JSONB values for at least one conflict-bearing tuple. Confirm the numbers are real (not a normalization artifact). If the conflict turns out to be a normalization difference rather than a genuine source disagreement, fix the quota normalizer rather than declaring victory.

## Testing

Same posture as the VNU-UET spec: data work, no new unit tests required.

- Existing pipeline unit tests must continue to pass.
- The HUST regression check (from Spec A) must still pass after NEU work — re-run as a sanity gate.

## Rollout

Execute steps 1–7 in order, each gated on its own acceptance. Merge in logical chunks:

1. **Source-registry + dictionary edits** (Steps 3 + 5) — one PR, configuration-only.
2. **Parser-profile or new-parser code** (Step 4) — separate PR if code lands.
3. **Acceptance SQL findings** (Steps 6 + 7) — documented in a "Findings" appendix or the merging PR's description.

If pre-flight fails irrecoverably (bail-outs exhausted), pause and escalate. The fallback "replace NEU with FTU" is a decision for the project owner, not the implementer.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| NEU's proposal PDF has poor table extraction or is a scanned image | Step 2 bail-out: switch secondary source to MOET aggregate or NEU news HTML. |
| NEU's HTML requires JS rendering | Confirm in Step 1 inspection. If quota only appears post-render, escalate before parser work. |
| Both NEU sources agree on all 2026 quota numbers (no conflict) | Step 2's last bail-out: escalate. Options include (a) replace NEU with FTU, (b) accept NEU as non-conflict-bearing coverage. |
| Program-name alignment ambiguous | Step 2 explicit check. Swap source pair before parser work. |
| Spec A migration not yet applied | Step 1 of execution checks `\d canonical_admission_records`. If new uniqueness constraint absent, halt and apply Spec A first. |
| Mid-execution drift if NEU updates its admission pages | Snapshot raw HTML into `raw_documents` at start of parser work, develop against the snapshot. |

## Tradeoffs

### Benefits

- Hardens the corpus against single-school pre-flight failure (VNU-UET).
- Adds a third real-data point to the architectural-generalization claim.
- Independent of VNU-UET work; can run in parallel.
- Reuses every existing pipeline layer; no new shared infrastructure.

### Costs

- Real-data ingestion risk: NEU might not have the same easily-discoverable cross-source disagreement that VNU-UET has via its parent-university proposal PDF. The "both sources agree" bail-out exists precisely because this risk is real.
- NEU sources may rely on JavaScript rendering more than VNU-UET, raising the chance of needing a heavier fetcher (out of scope for this spec — would be a separate fetcher spec).
- Three-school ingestion stretches the demo-prep timeline. Acceptable; the user explicitly chose three schools knowing this.

## Decision Summary

- **Phase name:** NEU 2026 admission data ingestion.
- **Scope:** source discovery → pre-flight → registry entries → parser/profile config (or thin parser) → normalization dictionary entries → canonical records → SQL acceptance.
- **Reliability posture:** real-data work; acceptance gated by SQL queries against the actual canonical-records state. Bail-outs documented for each major risk surface.
- **Explicitly deferred:** agent changes, schema changes, VNU-UET work, dataset dump export, cross-school acceptance.
- **Prerequisite:** Spec `2026-05-15-canonical-records-per-source-design.md` merged.
- **Parallel with:** `2026-05-15-vnu-uet-ingestion-design.md`.
- **Downstream consumer:** the conflict-aware advisory V1 spec's Slice 1 dataset gate.
