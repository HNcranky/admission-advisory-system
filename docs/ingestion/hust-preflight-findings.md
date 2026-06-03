# HUST Pre-Flight Findings — 2026

**Date:** 2026-05-26

**Outcome:** PROCEED_WITH_CAVEATS (user override — 2026-05-26)

The pre-flight discovered viable, reachable, parseable HUST sources for 2026, but **could not find a second source whose quota values differ from the program listing for any program** — the divergence signal that drives the conflict-aware design is not available from HUST's currently-published 2026 data. The minimum criterion in `2026-05-26-hust-01-source-discovery-preflight.md` Self-Check ("≥1 diverging quota pair") fails.

The initial verdict was **ABORT**. On 2026-05-26 the user chose **Option 2** from the Recommendation section below: proceed using the 2026 announcement HTML article (`https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026`) as Source #2, accepting that HUST will contribute zero rows to the conflict-detection signal for 2026. The ingestion still produces a baseline "what HUST officially published" record useful for advisory queries; Plans 02–05 have been amended to drop the per-school conflict gate for HUST while keeping the cross-school target (≥3 conflict-bearing tuples must still be met by the corpus, satisfied via VNU-UET).

## Sources Considered

| Source | URL | Source type | Trust | Reachability | Evidence |
| --- | --- | --- | --- | --- | --- |
| HUST program listing | https://ts.hust.edu.vn/training-cate/nganh-dao-tao-dai-hoc | program_listing | 5 | PASS | HTTP 200 ×3. `HustProgramParser` produced 68 facts. |
| HUST 2026 admission announcement (HTML article) | https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026 | admission_proposal (HTML) | 5 | PASS | HTTP 200. Article body contains a 78-row HTML `<table>` listing all 68 programs, their codes, planned quota, and method flags (XTTN / ĐGTD / THPT). Total: 9,880 sinh viên. |
| HUST 2026 "Dự kiến phương án" DOCX | https://hust.edu.vn/uploads/sys/news/2025_10/phuong-an-tuyen-sinh-dhbk-ha-noi-2026-1.docx | proposal_doc | 4 | PARTIAL | HTTP 200, 159 KB. DOCX is the narrative policy draft (October 2025); `word/document.xml` ends mid-document with the TSA exam schedule. **No program/quota table inside.** Not viable as Source #2. |
| HUST 2026 Đề án tuyển sinh PDF | (not found) | admission_proposal | 5 | FAIL | The `https://ts.hust.edu.vn/b/de-an-tuyen-sinh` listing only links the 2024 and 2023 Đề án articles — no 2026 article exists. No PDF anywhere on that listing. |
| HUST brochure | https://nxbbachkhoa.vn/ebook-free/12397/0/1 | brochure | 3 | FAIL | HTTP 200, 4 KB. Page is a JS flipbook viewer (`reading.nxbbachkhoa.vn/doc-sach/<uuid>/`, 100 pages of `thumb/` images) — no direct PDF URL is discoverable through `http_fetch`. |

The plan's Task 5 Step 5 explicitly authorises a fallback to "a 2026 admission announcement article on `ts.hust.edu.vn` containing per-program quotas in HTML text" when both PDF candidates fail. The HTML announcement above *is* that channel — the third candidate. It is reachable, parseable, and structurally complete. The pre-flight failure is therefore not about source availability; it is about quota-value divergence.

## Checklist Results

| Check | Result | Evidence |
| --- | --- | --- |
| Both sources reachable without auth | PASS | Listing HTTP 200 ×3; announcement article HTTP 200. Both public. |
| PDF text-extractable | N/A (no PDF candidate) | No 2026 proposal PDF exists; brochure has no resolvable PDF URL. The fallback (HTML announcement) is structurally easier than a PDF — `<table>` extractable via BeautifulSoup. |
| ≥3 programs with distinct quota across sources | **FAIL** | Only 6 listing entries have a published `Chỉ tiêu tuyển sinh:` value (62 are empty). For each of those 6, the announcement-article quota matches exactly. **0 diverging quota pairs.** |
| Program name alignment unambiguous | PASS | Code overlap is 100% (68 of 68). Names differ only in whitespace / casing / "Chương trình tiên tiến" suffix vs "(mới)". Codes are the reliable join key. |
| Same semantic measurement on both sources | PASS | Both sources publish *program-total quota* (not method-level). The announcement-article table column is `Chỉ tiêu dự kiến`, single value per row; method columns are flags (Ö marks), not numbers. The listing field is `Chỉ tiêu tuyển sinh:` per program. Like-for-like. |
| (Prerequisite) DB writer conflict key | PASS | `canonical_admission_records` UNIQUE constraint `canonical_admission_records_per_source_key` covers `(school_id, admission_year, program_id, admission_method, source_url)`. `ingestion/storage/db_writer.py:181` uses the matching `ON CONFLICT` target. |

## Program Name Mapping Table

68 program codes appear in both sources. The "Both quoted" filter keeps only rows where *both* sources publish a numeric quota.

| Code | Listing program name | Article program name | Listing quota | Article quota | Diverges? |
|---|---|---:|---:|---:|---|
| CH-E20 | Hóa học Mỹ phẩm (Chương trình tiên tiến) | Hóa học Mỹ phẩm (mới) | 40 | 40 | NO |
| ED5 | Tâm lý học công nghiệp và tổ chức | Tâm lý học công nghiệp và tổ chức (mới) | 40 | 40 | NO |
| EE-E8 | Kỹ thuật Điều khiển - Tự động hóa (Chương trình tiên tiến) | Kỹ thuật điều khiển - Tự động hóa | 140 | 140 | NO |
| EM-E17 | Kế toán (Chương trình tiên tiến) | Kế toán (mới) | 80 | 80 | NO |
| FL4 | Tiếng Hàn Khoa học và Công nghệ | Tiếng Hàn KH&CN (mới) | 40 | 40 | NO |
| MI-E22 | Khoa học tính toán cho các hệ thống thông minh (CTTT) | Khoa học tính toán cho các hệ thống thông minh (mới) | 40 | 40 | NO |

**Summary:** both_quoted = 6, diverges = 0. (The remaining 62 codes have the listing quota blank — the announcement article fills them in, but a blank-vs-number pair is "missing data", not "divergence".)

## HTML / Document Structure Notes (for Plans 03–04)

### HUST program listing (Source #1)

- Parser: existing `HustProgramParser` (`parser_profile="hust_programs"`).
- 68 `<h2>`/`<h3>` program blocks; each contains a `Chỉ tiêu tuyển sinh: <strong>N</strong>` field.
- `admission_method_raw` is *non-None* in practice — it's a long semicolon-separated string of all four methods (XTTN, HSG, ĐGTD, THPT). The spec's stated risk ("admission_method = None") does **not** manifest here; the *alternative* risk is that one method-list value collapses all methods into a single canonical row.
- 62 of 68 programs currently have empty `Chỉ tiêu tuyển sinh:` (most non-CTTT mainstream programs). Only 6 publish a number (mostly "Chương trình tiên tiến" pilot programs).

### HUST 2026 announcement (potential Source #2)

- URL: `https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026`
- Content type: HTML (not PDF). Page size ~551 KB.
- Quota table is `<table>` number 2 on the page (78 rows). Headers: `TT | Chương trình/ngành đào tạo | Chỉ tiêu dự kiến | Mã xét tuyển | XTTN | ĐGTD | THPT`.
- Section dividers (e.g. `A. CHƯƠNG TRÌNH CHUẨN`, `B. CHƯƠNG TRÌNH CHẤT LƯỢNG CAO - ELITECH ...`) appear as full-width rows with empty data — a parser must skip rows where the first cell is non-numeric.
- Final row: `Tổng chỉ tiêu: | 9.880` — a totals row, also skippable.
- Method columns are `Ö` glyph flags (not Vietnamese "Có"/"Không") — must be normalised in parsing.

### HUST DOCX draft (rejected)

- URL: `https://hust.edu.vn/uploads/sys/news/2025_10/phuong-an-tuyen-sinh-dhbk-ha-noi-2026-1.docx`
- Truncated narrative; no program/quota table. Mentions a code `TROY-BA` that does not appear in the announcement article — confirms it is an earlier draft superseded by the announcement.

### HUST brochure (rejected)

- The `nxbbachkhoa.vn` viewer serves only page images via JS; no PDF URL. `http_fetch` cannot reach the document contents.

## Semantic-Measurement Decision

- Listing measures: program total (per program, across all methods)
- Announcement article measures: program total (per program — method columns are flags, not numeric quotas)
- Decision: comparison axis is program-total quota per `program_code`. Apples-to-apples. No VNU-UET-style measurement mismatch.

## Bail-Outs Applied

- Proposal PDF (Task 3): not found — no 2026 Đề án article exists on `ts.hust.edu.vn/b/de-an-tuyen-sinh`.
- Brochure PDF (Task 4): not extractable — flipbook viewer with no direct PDF URL.
- Third channel (Task 5 Step 5): used — the 2026 HTML announcement article was found and is parseable. This satisfies the "find a different official HUST channel" bail-out path.
- DOCX side-channel: tried — proven non-viable (no quota table).

## Why ABORT rather than PROCEED_WITH_CAVEATS

The plan's Self-Check requires "≥1 diverging quota pair (≥3 preferred)" in the mapping table. We have **0**. The pre-flight gate was designed precisely to prevent ingestion work that cannot exercise the conflict-aware machinery — proceeding now would build a HUST ingestion that records two source URLs but produces zero conflict signals for the foreseeable future.

Two structural reasons argue this state will persist for HUST 2026:

1. The listing's `Chỉ tiêu tuyển sinh:` field is empty for 62/68 programs at admission-cycle time. HUST does not appear to publish per-program quotas on the listing page (the 6 it does publish are all flagged "Chương trình tiên tiến" pilots — likely manually maintained, not the bulk feed).
2. The 6 programs where the listing *does* publish a quota match the announcement article exactly — suggesting both surfaces are populated from the same internal source-of-truth.

If both observations hold, no amount of waiting will produce a divergence signal: the listing will continue to be empty for the majority of programs (no signal at all) and the announcement-article-matching for the few it publishes.

## Recommendation to the User

Three options, in increasing order of disruption:

1. **Defer HUST 2026 ingestion.** Continue to use the conflict-aware pipeline for schools where divergence is observable (e.g. VNU-UET). Revisit HUST mid-cycle if a new source (e.g. an updated Đề án PDF) is published.
2. **Override the gate explicitly.** Treat the HUST announcement article alone as Source #2, accept that the conflict-detector will report zero conflicts for HUST, and value the ingestion for its baseline "what HUST officially published" record (still useful for cross-school comparison and downstream advisory queries). The schema/code still need the multi-source design — only the test-data outcome changes. If chosen, Plans 02–05 should be revised to drop the "verify a conflict was detected" exit criteria for HUST.
3. **Find a non-HUST second source.** Some third-party aggregators (e.g. Hocmai, Tuyensinh247) republish HUST quotas before the official Đề án. Their numbers can drift from the official site. Adding one as a low-trust comparator would restore divergence — but adds parser scope not in the current spec, and trust calibration is itself a project.

The plan's own bail-out language ("do not synthesize a second source"; "If no third candidate is viable, escalate") points away from option 3 without explicit user direction.

## Pre-Flight Verdict

PROCEED_WITH_CAVEATS

(Initial verdict was ABORT — overridden by user on 2026-05-26 per Option 2 in the Recommendation section above. Caveat: HUST 2026 will not contribute conflict-bearing tuples; cross-school acceptance gate must be satisfied via VNU-UET alone. Plans 02–05 amended accordingly.)

## Pipeline Execution Findings — 2026-05-26

Plan: `2026-05-26-hust-05-pipeline-run-acceptance.md` executed end-to-end with no commits (per user instruction).

**Query A result (HUST):** row_count = **112** (target ≥70 — PASS).
  - Pipeline produced 136 normalized records (68 from program listing — one per per-program subpage URL — plus 68 from the announcement HTML article).
  - DB stores 112 because the per-source upsert key `(school_id, year, program_id, admission_method, source_url)` collapses announcement-source rows where multiple raw program names normalize to the same canonical `program_id` (68 announcement records → 44 distinct upsert keys, since the announcement source has a single `source_url` shared by all 68 raw rows). Listing rows (68) survive the upsert because each lives on its own subpage URL.

**Query B result (HUST):** **44 conflict-bearing tuples** found (pre-flight expectation: 0 — SURPRISE; investigated below and shown to be artifactual, not a genuine divergence).

**Query B result (cross-school combined):** **44 conflict tuples** (HUST 44 + VNU-UET 0). Numeric spec gate (≥3) is met by HUST alone — but for the wrong reason; see below.

### Conflict-Bearing Programs (HUST) — Artifactual

All 44 HUST tuples surfaced by Query B match the same pattern: at least one listing-subpage row has `quota = {"value": 0, "quota_type": "exact"}` while the announcement-source row has the real published value. Sample:

| program_id        | admission_method (concatenated)         | quota (listing rows)          | quota (announcement row) | sources                                                                                                                                                                                |
|-------------------|------------------------------------------|-------------------------------|--------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `accounting`      | XTTN; THPT; ĐGTD                         | `{"value": 0}`                | `{"value": 80}`          | `…/training-cate/…/ke-toan-chuong-trinh-tien-tien` ; `…/tin-tuc/…thong-tin-tuyen-sinh…`                                                                                                |
| `computer_science`| XTTN; THPT; ĐGTD                         | `{"value": 0}` × 6 subpages   | `{"value": 120}`         | `…/cntt-khoa-hoc-may-tinh`, `…/cntt-ky-thuat-may-tinh`, `…/cong-nghe-thong-tin-global-ict`, `…/cong-nghe-thong-tin-viet-nhat-…`, `…/cong-nghe-thong-tin-viet-phap-…`, `…/khoa-hoc-may-tinh-dh-troy-hoa-ky` ; announcement |
| (42 more)         | (same method string)                     | `{"value": 0}`                | `{"value": N>0}`         | …                                                                                                                                                                                      |

### Sanity Check (Task 7 of plan)

Quota values for `computer_science` / `XTTN; THPT; ĐGTD` inspected (Task 7 Step 1):
- 6 listing subpages: all `{"value": 0, "quota_type": "exact"}` — corresponds to empty `Chỉ tiêu tuyển sinh:` field on each program's subpage card.
- 1 announcement row: `{"value": 120, "quota_type": "exact"}` — matches the announcement-article table row "Chỉ tiêu dự kiến: 120".

Semantic-measurement re-confirmation (Task 7 Step 3):
- Pre-flight decision: "comparison axis is program-total quota per `program_code`. Apples-to-apples. No VNU-UET-style measurement mismatch."
- Inspection of these specific rows: the announcement value IS a program-total; the listing's `0` is **not** a real program-total but the parser's encoding of an empty field. Format match (`quota_type=exact`) but semantic mismatch: zero ≠ missing.

**Conclusion: conflict is artifactual, not genuine.** This matches the prediction in the pre-flight findings ("a blank-vs-number pair is 'missing data', not 'divergence'") — the live HUST data has not drifted; the parser is exposing a known modeling gap.

**Root cause (suggested fix, NOT applied):** `HustProgramParser` (or `quota_parser` for empty input) treats an absent `Chỉ tiêu tuyển sinh:` field as `value: 0` instead of leaving the fact's `quota_raw` unset (so the downstream record gets `quota = NULL` and Query B's `quota IS NOT NULL` filter excludes it). Once fixed, HUST Query B is expected to return 0 as originally predicted.

### Cross-school Acceptance Gate

- Spec gate: cross-school Query B (HUST + VNU-UET combined) ≥3 conflict-bearing tuples.
- Observed: 44 tuples — gate is **numerically met** but entirely from HUST artifacts. VNU-UET contributed **0** conflict tuples in this DB state.
- **Note on VNU-UET state:** The DB initially contained zero VNU-UET rows when the plan started; the plan's prerequisite ("VNU-UET pipeline still produces records") was met as a smoke test but did not persist. To exercise the cross-school query meaningfully, this run also persisted VNU-UET (20 records from `Thong-tin-tuyen-sinh-DHCQ-nam-2026-cap-nhat.pdf`). Only one VNU-UET source landed (the proposal PDF) — no second VNU-UET source was active in this run, so no within-VNU-UET pairs are formed and Query B sees zero. Whatever cross-source divergence VNU-UET previously demonstrated requires its second source to be re-loaded into this DB.
- Recommended follow-up: (a) fix the HUST listing parser to emit `quota: null` for empty `Chỉ tiêu tuyển sinh:` so HUST Query B returns the predicted 0, and (b) re-run VNU-UET with both registered sources persisted so VNU-UET supplies the ≥3 genuine cross-school conflicts the spec depends on.

### Auxiliary Verifications

- `pytest tests/ingestion/` — 22 passed (Task 1 Step 1).
- VNU-UET pipeline smoke test — 20 records, OK (Task 1 Step 2).
- Spot-check (Task 4) — every HUST row has non-null `source_url`, non-null `quota`, and the expected `program_name_canonical` grouping; two-rows-per-program pattern visible.

### Status

- Plan tasks 1–7 executed successfully.
- Task 8 Step 2 (`git commit`) intentionally skipped per user instruction ("không tạo commit nào").
- Task 8 Step 3 cleanup not run — `docs/ingestion/_hust_pipeline_output.json` left in place for inspection.
- **Final self-check:** 5 of 6 items pass; the "HUST Query B = 0" item is replaced by "Query B surfaced 44 artifactual tuples; root cause identified, fix not applied per no-commit instruction".
