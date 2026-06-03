# NEU Pre-Flight Findings - 2026

**Date:** 2026-05-26

**Outcome:** BAIL-OUT

The NEU source discovery found the official 2026 admission decision page and the official 2026 DHCQ PDF, but the planned source pair does not satisfy the pre-flight acceptance gates. The original admission homepage is reachable but does not expose 2026 program quotas in static HTML, and the official 2026 DHCQ PDF quota table is image/scanned for `pdfplumber` purposes. No source pair with parser-extractable quota values and at least one confirmed quota divergence was found.

## Sources Confirmed

| Source | URL | Type | Trust | Reachable | Evidence |
| --- | --- | --- | ---: | --- | --- |
| NEU admission homepage | https://tuyensinh.neu.edu.vn/ | admission_homepage | 4 | YES_WITH_CAVEAT | HTTP 200 returned three times. Raw first response is a Cloudrity cookie challenge; with the cookie header, static HTML loads but exposes 2025/banner content rather than 2026 quota tables. |
| NEU official 2026 decision page | https://neu.edu.vn/quyet-dinh-ve-viec-ban-hanh-thong-tin-tuyen-sinh-trinh-do-dai-hoc-chinh-quy-nam-2026-cua-dai-hoc-kinh-te-quoc-dan/ | admission_announcement | 5 | YES | Official NEU page dated 2026-03-06. Links the 2026 DHCQ PDF. |
| NEU 2026 DHCQ PDF | https://neu.edu.vn/wp-content/uploads/2026/03/Thong-tin-TS-nam-2026-hinh-thuc-dao-tao-DHCQ.pdf | admission_proposal_pdf | 5 | YES | Downloaded to `%TEMP%\neu_proposal_2026.pdf`, size 8,868,793 bytes, 11 pages. Contains quota tables visually, but `pdfplumber` extracted empty text from pages 1-5 and the quota-table pages. |
| NEU school/program book page | https://neu.edu.vn/thong-bao-ve-viec-ban-hanh-va-cong-bo-sach-gioi-thieu-cac-nganh-chuong-trinh-dao-tao-dai-hoc-chinh-quy-tuyen-sinh-nam-2026-cua-dai-hoc-kinh-te-quoc-dan/ | program_book_announcement | 4 | YES | Official NEU page dated 2026-05-09. Links a text-extractable 82-page program book, but the book describes programs/curricula rather than a quota table. |
| NEU program book PDF | https://neu.edu.vn/wp-content/uploads/2026/05/GT-Nganh-va-CTDT-DHCQ-2026-3_compressed-1.pdf | program_book_pdf | 4 | YES | `pdfplumber` extracts readable text and program names. No quota table found in sampled contents; not a replacement for the admission proposal quota table. |
| NCT NEU 2026 article mirror | https://nct.neu.edu.vn/post/cong-bo-thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026-cua-dai-hoc-kinh-te-quoc-dan | official_unit_article | 4 | YES | Official NEU Trường Công nghệ article dated 2026-03-05. Links the same NEU decision page and summarizes that 2026 information includes quotas, methods, program list, and combinations. |

## Checklist Results

| Check | Result | Evidence |
| --- | --- | --- |
| Both planned sources reachable without auth | PARTIAL | `https://tuyensinh.neu.edu.vn/` returned HTTP 200 three times, but requires a cookie challenge for usable HTML. The official NEU decision page and PDF are public and reachable. |
| PDF is text-extractable | FAIL | `pdfplumber.open("%TEMP%/neu_proposal_2026.pdf")` reported 11 pages, but `page.extract_text()` returned empty strings for pages 1-5. The visible quota table appears on pages 4-7, but it is image/scanned for parser purposes. |
| >=3 programs with distinct quota across sources | FAIL | No second parser-extractable quota source was found. Visual PDF rows can be read manually, but the homepage/static HTML does not expose 2026 quota rows and the program book has no quota table. |
| Program name alignment unambiguous | PARTIAL | Visual PDF rows are unambiguous for sampled programs (`Kế toán`, `Marketing`, `Tài chính - Ngân hàng`, `Kinh doanh quốc tế`, etc.). Cross-source quota mapping could not be completed because the second quota-bearing source is missing. |
| DB prerequisite: canonical per-source key | PARTIAL | Repo evidence passes: `ingestion/storage/db_writer.py` uses `ON CONFLICT (school_id, admission_year, program_id, admission_method, source_url)`, and migration `db/migrations/010_canonical_records_per_source.sql` defines `canonical_admission_records_per_source_key`. Live DB verification failed because `psql` is not installed and Python `psycopg2` reached localhost:5432 but default credentials were rejected for user `postgres`. |

## Program Name Mapping Table

No accepted cross-source quota mapping table could be produced. The table below records manually verified PDF rows from the official 2026 DHCQ PDF screenshots so Plan 02 can reuse the discovered source URL if OCR/browser extraction is later approved.

| NEU source name | PDF name | Quota homepage/static source | Quota PDF visual | Diverges? |
| --- | --- | ---: | ---: | --- |
| N/A - no static quota source | Kế toán | N/A | 150 | UNKNOWN |
| N/A - no static quota source | Marketing | N/A | 100 | UNKNOWN |
| N/A - no static quota source | Tài chính - Ngân hàng | N/A | 230 | UNKNOWN |
| N/A - no static quota source | Kinh doanh quốc tế | N/A | 100 | UNKNOWN |
| N/A - no static quota source | Quản trị kinh doanh | N/A | 180 | UNKNOWN |
| N/A - no static quota source | Logistics và Quản lý chuỗi cung ứng | N/A | 100 | UNKNOWN |
| N/A - no static quota source | Khoa học dữ liệu | N/A | 70 | UNKNOWN |
| N/A - no static quota source | Trí tuệ nhân tạo | N/A | 80 | UNKNOWN |

## HTML Structure Notes (for Plan 03 parser work)

NEU admission homepage:

- URL inspected: `https://tuyensinh.neu.edu.vn/`
- Reachability: HTTP 200 x3.
- Initial raw response: 177-byte Cloudrity cookie challenge setting `D1N=71ffd2f0616e697fc9a987ec17df29f6`.
- Cookie-header response size: about 23 KB of XHTML/ASP.NET-style HTML.
- 2026 quota data in static response: NO. Static content included title `Tuyển Sinh` and slider JSON referencing `THÔNG TIN TUYỂN SINH ĐẠI HỌC CHÍNH QUY 2025`.
- Program container selector: not identified for 2026 quota data because no 2026 static quota table was present.
- JS-rendered / challenge-gated: YES for the initial fetch path. Treat `fetch_strategy: "browser"` or a cookie-aware fetcher as a risk if this source remains in scope.

NEU official decision page:

- URL: `https://neu.edu.vn/quyet-dinh-ve-viec-ban-hanh-thong-tin-tuyen-sinh-trinh-do-dai-hoc-chinh-quy-nam-2026-cua-dai-hoc-kinh-te-quoc-dan/`
- Structure: WordPress article page.
- Relevant content area: article body around the links titled `Thông tin TS năm 2026 hình thức đào tạo ĐHCQ`.
- DHCQ PDF URL: `https://neu.edu.vn/wp-content/uploads/2026/03/Thong-tin-TS-nam-2026-hinh-thuc-dao-tao-DHCQ.pdf`

NEU proposal PDF:

- Program quota table starts visually on PDF page 4 and continues through page 7.
- Table columns: `TT | Mã xét tuyển | Tên chương trình, ngành xét tuyển | Mã ngành | Tên ngành | Số lượng tuyển sinh`.
- Visual total on page 7: `Cộng 8780`.
- `pdfplumber` extraction quality: POOR for the proposal PDF. It returns empty text for the quota-table pages, so the current default PDF parser would fail without OCR.

NEU program book PDF:

- URL: `https://neu.edu.vn/wp-content/uploads/2026/05/GT-Nganh-va-CTDT-DHCQ-2026-3_compressed-1.pdf`
- `pdfplumber` extraction quality: GOOD for text and program names.
- Not a quota source based on sampled pages; it is a program/curriculum guide.

## Bail-Outs Applied

- Official PDF found but excluded for default parser work because it is scanned/image-based for `pdfplumber`.
- Original homepage retained as a reachability finding, but excluded as a quota source because static HTML did not expose 2026 program/quota rows.
- Official NEU decision page and NCT mirror were used to locate the correct 2026 PDF, but they do not provide a parseable quota table in HTML.
- Official NEU program book was tested as a replacement PDF. It is text-extractable, but it is not quota-bearing.
- No MOET or third-party aggregate was adopted as a replacement because the plan asked for NEU official source discovery and no official replacement with per-program quotas in parseable HTML was found.

## Pre-Flight Verdict

BAIL-OUT. Do not proceed to NEU parser work under the current Plan 02 assumptions.

Recommended next action: either approve an OCR/browser-rendered extraction path for the official NEU scanned PDF, or replace NEU with another school/source pair that has two parser-extractable quota-bearing sources and at least one confirmed quota divergence.
