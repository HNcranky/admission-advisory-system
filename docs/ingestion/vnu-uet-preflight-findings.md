# VNU-UET Pre-Flight Findings - 2026

Date: 2026-05-16

Outcome: PASS_WITH_CAVEATS

Pre-flight source discovery passed for the official VNU-UET 2026 admission article and its linked official PDF. Caveats: the original planned URL returned 404, the originally requested VNU-wide proposal PDF was not found, and the live DB schema was not verified because `psql` is not installed/on PATH. The official UET PDF linked from the public UET article was used as the parseable proposal-like source. The plan commit step was intentionally not performed because the user requested no commits.

## Sources Confirmed

| Source | URL | Source type | Trust | Reachability | Evidence |
| --- | --- | --- | --- | --- | --- |
| Original planned UET admissions URL | https://uet.vnu.edu.vn/tuyen-sinh-dai-hoc/ | admission_homepage | 4 | FAIL | Returned HTTP 404 via curl. |
| UET admissions fallback URL | https://uet.vnu.edu.vn/tuyen-sinh/ | admission_homepage | 4 | PASS | Returned HTTP 200 three times. |
| Official UET 2026 article | https://uet.vnu.edu.vn/truong-dai-hoc-cong-nghe-dhqghn-ma-truong-qhi-tuyen-sinh-nam-2026-bac-dai-hoc-2/ | admission_homepage/article | 4 | PASS | Returned HTTP 200 three times. Public article, no auth observed. Title: "Trường Đại học Công nghệ, ĐHQGHN (Mã trường QHI): Tuyển sinh năm 2026 bậc đại học". Published 2026-04-02. |
| Official UET linked PDF | https://tuyensinh.uet.vnu.edu.vn/wp-content/images/Thong-tin-tuyen-sinh-DHCQ-nam-2026-cap-nhat.pdf | proposal_pdf | 5 | PASS | Linked from the official article. Downloaded locally to `%TEMP%\vnuhn_proposal_2026.pdf`, size 1,908,053 bytes. |

## Checklist Results

| Check | Result | Evidence |
| --- | --- | --- |
| Both sources reachable without auth | PASS_WITH_CAVEAT | The fallback admissions URL and resolved 2026 article URL returned HTTP 200 three times each. The original planned URL returned HTTP 404. Article and PDF were public; no auth was observed. |
| PDF text-extractable | PASS | `pdfplumber` opened the PDF successfully: 11 pages. Page 1 extracted readable Vietnamese text. Page 4 extracted the reserved/dự bị table. Pages 5-6 extracted the main quota table. Extraction quality: GOOD. |
| At least 3 programs with distinct quota across sources | PASS | 20 method-level divergent rows were identified using the UET article visible `dự bị đại học` method/allocation table versus the PDF main quota table. |
| Program name alignment unambiguous | PASS | Names/codes align. Differences are limited to case, punctuation, asterisk pilot-program markers, or parenthetical program details. |
| DB writer conflict key pre-flight | PREREQUISITE_NOT_VERIFIED | `psql` is not installed/on PATH, so the live DB schema was not verified. Repo evidence exists: `db/migrations/010_canonical_records_per_source.sql` defines `UNIQUE (school_id, admission_year, program_id, admission_method, source_url)`, and `ingestion/storage/db_writer.py` line 181 uses `ON CONFLICT (school_id, admission_year, program_id, admission_method, source_url)`. |

## Program Name Mapping Table

This is a method-level comparison. The UET article source quota is the visible `dự bị đại học` method/allocation quota, while the PDF source quota is the PDF main quota table.

| UET article program name | PDF program name | UET method quota | PDF full quota | Match |
| --- | --- | ---: | ---: | --- |
| Công nghệ thông tin | Công nghệ thông tin | 3 | 460 | YES |
| Kỹ thuật máy tính | Kỹ thuật máy tính | 3 | 400 | YES |
| Khoa học máy tính | Khoa học máy tính | 3 | 400 | YES |
| Trí tuệ nhân tạo | Trí tuệ nhân tạo | 3 | 320 | YES |
| Hệ thống thông tin | Hệ thống thông tin | 2 | 240 | YES |
| Mạng máy tính và truyền thông dữ liệu | Mạng máy tính và truyền thông dữ liệu | 1 | 120 | YES |
| Vật lý kỹ thuật | Vật lý kỹ thuật | 3 | 160 | YES |
| Cơ kỹ thuật | Cơ kỹ thuật | 1 | 60 | YES |
| Công nghệ kỹ thuật xây dựng | Công nghệ kỹ thuật xây dựng | 2 | 160 | YES |
| Công nghệ kỹ thuật cơ điện tử | Công nghệ kỹ thuật cơ - điện tử | 2 | 160 | YES |
| Công nghệ hàng không vũ trụ | Công nghệ hàng không vũ trụ* | 2 | 120 | YES |
| Công nghệ kỹ thuật điện tử - viễn thông | Công nghệ kỹ thuật điện tử – viễn thông | 3 | 480 | YES |
| Công nghệ nông nghiệp | Công nghệ nông nghiệp* | 1 | 60 | YES |
| Kỹ thuật điều khiển và tự động hóa | Kỹ thuật điều khiển và tự động hoá | 2 | 140 | YES |
| Kỹ thuật năng lượng | Kỹ thuật năng lượng* | 2 | 60 | YES |
| Kỹ thuật Robot | Kỹ thuật Robot* | 2 | 140 | YES |
| Thiết kế công nghiệp và đồ họa | Thiết kế công nghiệp và Đồ họa* | 2 | 240 | YES |
| Công nghệ vật liệu | Công nghệ vật liệu (Chương trình Công nghệ vật liệu và Vi điện tử) | 1 | 120 | YES |
| Khoa học dữ liệu | Khoa học dữ liệu (Chương trình Khoa học và Kỹ thuật dữ liệu) | 1 | 120 | YES |
| Công nghệ sinh học | Công nghệ sinh học (Chương trình Công nghệ kỹ thuật sinh học) | 1 | 60 | YES |

## HTML Structure Notes

- The direct source HTML appears to be a WordPress article body.
- Page content extraction shows the article includes the method share table and the `dự bị` table.
- Selector approximation for parser implementation: `.elementor-widget-theme-post-content` / `.entry-content`.
- Repeated table rows appear to be rendered as WordPress table content.
- Exact DOM class should be confirmed during parser implementation because current inspection used text extraction rather than browser devtools.

## Bail-Outs Applied

- The original planned URL `https://uet.vnu.edu.vn/tuyen-sinh-dai-hoc/` returned HTTP 404, so source discovery used fallback URL `https://uet.vnu.edu.vn/tuyen-sinh/`.
- The resolved official 2026 article URL was used after confirming repeated HTTP 200 responses.
- The originally requested VNU-wide proposal PDF was not found. The official UET PDF linked from the article was used as the parseable proposal-like source.
- Live DB schema verification was skipped because `psql` is not installed/on PATH; repo migration and writer evidence were recorded as a prerequisite note instead.
- No commit was created; the commit step was intentionally skipped per user instruction.

## Pipeline Execution Findings - 2026-05-16

**Query A result:** row_count = 40
**Query B result:** 20 conflict-bearing tuples found

The full VNU-UET pipeline produced 40 normalized records: 20 from the public UET admissions page and 20 from the official linked PDF. Records were upserted into `canonical_admission_records` with distinct `source_url` values for the same `program_id` / `admission_method` pairs.

### Conflict-Bearing Programs

| program_id | admission_method | quota (homepage source) | quota (PDF source) |
|------------|------------------|-------------------------|--------------------|
| CN1 | Xét tuyển tài năng | 3 | 460 |
| CN10 | Xét tuyển tài năng | 1 | 60 |
| CN11 | Xét tuyển tài năng | 2 | 140 |
| CN12 | Xét tuyển tài năng | 3 | 320 |
| CN13 | Xét tuyển tài năng | 2 | 60 |
| CN14 | Xét tuyển tài năng | 2 | 60 |
| CN15 | Xét tuyển tài năng | 1 | 240 |
| CN17 | Xét tuyển tài năng | 2 | 120 |
| CN18 | Xét tuyển tài năng | 2 | 140 |
| CN19 | Xét tuyển tài năng | 1 | 240 |
| CN2 | Xét tuyển tài năng | 3 | 400 |
| CN20 | Xét tuyển tài năng | 1 | 120 |
| CN21 | Xét tuyển tài năng | 1 | 120 |
| CN3 | Xét tuyển tài năng | 3 | 160 |
| CN4 | Xét tuyển tài năng | 1 | 60 |
| CN5 | Xét tuyển tài năng | 2 | 160 |
| CN6 | Xét tuyển tài năng | 2 | 160 |
| CN7 | Xét tuyển tài năng | 2 | 120 |
| CN8 | Xét tuyển tài năng | 3 | 400 |
| CN9 | Xét tuyển tài năng | 3 | 480 |

### Sanity Check

Quota values for `CN1` / `Xét tuyển tài năng`:

- Homepage source: `{"value": 3, "quota_type": "exact"}` - matches the homepage allocation table value `3`.
- PDF source: `{"value": 460, "quota_type": "exact"}` - matches the PDF main quota table value `460`.

Both values normalize to the same JSONB shape and quota type. The conflict signal is therefore not caused by a quota parser format mismatch. It reflects the pre-flight source comparison: homepage method/allocation quota versus PDF main quota.

Conclusion: SQL acceptance gate PASSED. No commit was created because the user explicitly requested no commits.

## Conflict-Aware Slice 2 Re-Run - 2026-05-27

Outcome: PARTIAL_PASS_BLOCKED_ON_REAL_CONFLICT_QUALITY

Environment:

- Docker Compose Postgres was started from this repo.
- Host port `5432` conflicted with an existing local `postgres` process, so the compose DB was recreated on host port `55432`.
- Commands were run with `DB_HOST=127.0.0.1`, `DB_PORT=55432`, and `PYTHONIOENCODING=utf-8`.
- After uninstalling the local PostgreSQL service, the compose DB was recreated again on the default host port `5432`. The default app config `localhost:5432` then connected to the compose DB successfully.

Schema verification:

- `python -m db.setup_db` applied migrations `001` through `010` successfully.
- `canonical_admission_records_per_source_key` exists with index definition:
  `CREATE UNIQUE INDEX canonical_admission_records_per_source_key ON public.canonical_admission_records USING btree (school_id, admission_year, program_id, admission_method, source_url)`.

Ingestion execution:

- `python -m ingestion.main --school vnu_uet` completed and produced 20 normalized records, but the CLI prints records and does not persist them.
- `python -m ingestion.main --school hust` completed and produced 136 normalized records, but the CLI prints records and does not persist them.
- For DB acceptance, the repo's integration path was used: `IngestionPipeline().run_for_school(...)` followed by `save_canonical_records(records)`.
- Persisted records: `vnu_uet` produced 20 / saved 20; `hust` produced 136 / saved 136.

Acceptance query results:

- Query A returned `hust` row_count = 112 and `vnu_uet` row_count = 20 for admission year 2026.
- Query B returned 44 candidate conflict-bearing tuples.
- Re-running Query A and Query B on default `localhost:5432` returned the same results: `hust` row_count = 112, `vnu_uet` row_count = 20, Query B candidate count = 44, and non-zero conflict count = 0.
- Spot-check of the first tuple, `hust/accounting`, showed:
  - Main announcement source quota: `{"value": 80, "quota_type": "exact"}`.
  - Program detail source quota: `{"value": 0, "quota_type": "exact"}`.
- This is not an acceptable like-for-like quota conflict. The `0` value appears to be a missing/placeholder quota extraction artifact from HUST detail pages.
- Filtering candidate tuples to exclude any zero-valued quota artifacts returned 0 non-zero conflict tuples.

Conclusion:

- Schema and writer acceptance passed.
- Real ingestion produced rows for both target schools.
- The real conflict-quality gate did not pass because Query B candidates are currently driven by `0` quota artifacts, not trustworthy quota divergence.
- `tests/e2e/fixtures/real_dataset_dump.sql` was not exported. The parser/normalizer should be fixed or sources re-curated before exporting a real fixture.
- No commit was created.
