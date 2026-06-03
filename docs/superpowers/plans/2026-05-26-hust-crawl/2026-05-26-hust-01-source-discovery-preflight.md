# HUST Source Discovery & Pre-Flight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover and manually verify HUST's 2026 admission sources, confirm two reachable parseable sources publishing the same semantic measurement with differing quota values, and document findings before any code is written.

**Architecture:** Pure investigation — browse live URLs, extract text from candidate PDFs, compare program names side-by-side, then commit a findings document. No source-registry or parser changes in this plan; those follow in Plans 02–05.

**Tech Stack:** `curl` (or `ingestion/fetchers/http_fetcher.py` for SSL-tricky hosts), `pdfplumber` for PDF text extractability check, `psql` (via `docker compose exec`) for prerequisite verification, Markdown for findings document.

**Prerequisite:** Spec `2026-05-15-canonical-records-per-source-design.md` is merged (migration `010_canonical_records_per_source.sql` applied; `db_writer.py` uses the new ON CONFLICT target). Plan 01 verifies both in Task 1.

---

### Task 1: Verify Prerequisite — Canonical Records Migration Applied

**Files:**
- No file changes. Database inspection only.

- [ ] **Step 1: Ensure the Docker DB is running**

Run:
```powershell
docker compose ps
```

If the `advisory-db` container is not listed, start it:
```powershell
docker compose up -d --wait db
```

- [ ] **Step 2: Inspect the canonical_admission_records constraint via psql**

Run:
```powershell
docker compose exec -T db psql -U postgres -d admission -c "\d canonical_admission_records"
```

Expected: the output lists a UNIQUE constraint named `canonical_admission_records_per_source_unique` covering `(school_id, admission_year, program_id, admission_method, source_url)`. The `source_url` column must appear in the table definition.

If the `source_url` column does **not** appear, stop here. The Spec A migration (`010_canonical_records_per_source.sql`) has not been applied. Apply it first via `python -m db.setup_db` and re-run this step.

- [ ] **Step 3: Confirm db_writer uses the new ON CONFLICT target**

Run:
```powershell
Select-String -Path ingestion/storage/db_writer.py -Pattern "ON CONFLICT"
```

Expected: at least one line of the form:
```
ON CONFLICT (school_id, admission_year, program_id, admission_method, source_url)
```

If the only ON CONFLICT clause targets the 4-tuple `(school_id, admission_year, program_id, admission_method)` without `source_url`, halt and complete Spec A integration before continuing.

---

### Task 2: Inspect HUST Program Listing (Source #1 Candidate)

**Files:**
- No changes. Observation only.

- [ ] **Step 1: Fetch the HUST program listing**

Use the project's HTTP fetcher (it handles the HUST SSL cert chain that some clients reject):

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from ingestion.fetchers.http_fetcher import http_fetch
r = http_fetch('https://ts.hust.edu.vn/training-cate/nganh-dao-tao-dai-hoc')
print('status:', r.http_status)
print('content_type:', r.content_type)
print('size:', len(r.raw_content))
"
```

Expected: `status: 200`, `content_type: text/html...`, `size: 400000+` (the page is large, ~500 KB observed at spec time).

If status is not 200, document the failure and treat this source as unreachable for the bail-out path in Task 5.

- [ ] **Step 2: Verify the existing `hust_programs` parser still produces facts**

Run:
```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.parsers.hust_program_parser import HustProgramParser
r = http_fetch('https://ts.hust.edu.vn/training-cate/nganh-dao-tao-dai-hoc')
parser = HustProgramParser()
facts = parser.parse(r.raw_content, source_url=r.url)
print(f'facts: {len(facts)}')
for f in facts[:5]:
    print(f'  program_name={f.program_name!r}')
    print(f'  program_code={f.program_code!r}')
    print(f'  quota_raw={f.quota_raw!r}')
    print(f'  method_raw={f.admission_method_raw!r}')
    print()
"
```

Expected: ≥10 facts. Each fact has a non-empty `program_name` (Vietnamese text like "Khoa học Máy tính"), a non-empty `program_code` like `IT1`, and a `quota_raw` digit string.

If `admission_method_raw` is `None` for all facts, that is the known HUST risk called out in the spec ("admission_method = None collapses the conflict signal"). Note this — Plan 03 Task 4 will address it via parser tuning.

- [ ] **Step 3: Repeated reachability check (no rate limiting)**

Run three times within 30 seconds:
```powershell
1..3 | ForEach-Object {
  $env:PYTHONIOENCODING="utf-8"
  .venv/Scripts/python.exe -c "from ingestion.fetchers.http_fetcher import http_fetch; r = http_fetch('https://ts.hust.edu.vn/training-cate/nganh-dao-tao-dai-hoc'); print(r.http_status)"
}
```

Expected: `200` each time. If you see `429` or `503`, document this — the source may need throttling.

---

### Task 3: Hunt for HUST 2026 Admission Proposal PDF (Source #2 Candidate A)

**Files:**
- No changes. Observation only.

- [ ] **Step 1: Inspect the de-an-tuyen-sinh listing for 2026 PDF links**

Run:
```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from ingestion.fetchers.http_fetcher import http_fetch
from bs4 import BeautifulSoup
import re
r = http_fetch('https://ts.hust.edu.vn/b/de-an-tuyen-sinh')
soup = BeautifulSoup(r.raw_content, 'html.parser')
print('Page title:', soup.title.get_text() if soup.title else '?')
print()
print('PDF links on page:')
pdfs = sorted({a['href'] for a in soup.find_all('a', href=True) if a['href'].lower().endswith('.pdf')})
for p in pdfs:
    print(' ', p)
print()
print('Article links mentioning 2026:')
for a in soup.find_all('a', href=True):
    txt = a.get_text(strip=True)
    if '2026' in txt:
        print(f'  {a[\"href\"]} | {txt[:120]}')
"
```

Document every PDF link and every article whose anchor text mentions 2026. If there are no direct PDF links, deeper inspection of articles is needed (Step 2).

- [ ] **Step 2: Drill into each 2026-mentioning article for an embedded PDF**

For each article URL captured in Step 1, fetch it and search for PDF links inside the article body:

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from ingestion.fetchers.http_fetcher import http_fetch
from bs4 import BeautifulSoup
url = '<ARTICLE_URL_HERE>'
r = http_fetch(url)
soup = BeautifulSoup(r.raw_content, 'html.parser')
print('Article title:', soup.title.get_text() if soup.title else '?')
print('PDF links inside the article:')
for a in soup.find_all('a', href=True):
    href = a['href']
    if href.lower().endswith('.pdf') or 'pdf' in href.lower():
        print(f'  {href}')
        print(f'    anchor text: {a.get_text(strip=True)[:120]}')
"
```

Repeat for each candidate article. If you find a PDF whose anchor text or filename suggests "đề án tuyển sinh 2026", capture its full URL — that's the source #2 candidate.

- [ ] **Step 3: If found, verify the PDF is text-extractable**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from ingestion.fetchers.http_fetcher import http_fetch
import io, pdfplumber
pdf_url = '<PROPOSAL_PDF_URL>'
r = http_fetch(pdf_url)
print('status:', r.http_status, 'size:', len(r.raw_content))
with pdfplumber.open(io.BytesIO(r.raw_content)) as pdf:
    print('pages:', len(pdf.pages))
    for i, page in enumerate(pdf.pages[:8]):
        text = page.extract_text() or ''
        print(f'--- page {i+1} ({len(text)} chars) ---')
        print(text[:400])
        print()
"
```

Expected: pages render readable Vietnamese text including program names and digit columns. If pages return empty strings or unreadable characters, the PDF is scanned — proceed to Task 4 (brochure fallback).

- [ ] **Step 4: If no proposal PDF is found**

Document the search attempts in your notes and continue to Task 4. The brochure PDF is the documented bail-out per the spec.

---

### Task 4: Inspect HUST Brochure PDF (Source #2 Candidate B — Bail-Out)

**Files:**
- No changes. Observation only.

This task runs unconditionally as a fallback discovery — even if Task 3 succeeded, knowing whether the brochure is also viable gives the implementer a choice in Plan 02.

- [ ] **Step 1: Resolve the brochure PDF URL**

The brochure landing page is `https://nxbbachkhoa.vn/ebook-free/12397/0/1` ("Brochure Thông tin tuyển sinh"). It serves a viewer page, not the PDF directly. Inspect the page for an embedded PDF URL:

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from ingestion.fetchers.http_fetcher import http_fetch
from bs4 import BeautifulSoup
import re
r = http_fetch('https://nxbbachkhoa.vn/ebook-free/12397/0/1')
print('status:', r.http_status, 'size:', len(r.raw_content))
html = r.raw_content.decode('utf-8', errors='replace')
# look for embedded PDF urls
candidates = sorted(set(re.findall(r'https?://[^\"\\\'\\s<>]+\\.pdf', html, re.I)))
for c in candidates:
    print(' pdf:', c)
# fallback: embed/iframe sources
soup = BeautifulSoup(r.raw_content, 'html.parser')
for tag in soup.find_all(['embed', 'iframe', 'object']):
    src = tag.get('src') or tag.get('data')
    if src:
        print(' embed/iframe:', src)
"
```

Document the resolved PDF URL (if any). If no PDF URL is discoverable, the brochure can't be used directly through `http_fetch` — note this and treat as another bail-out.

- [ ] **Step 2: Text-extractability check (if brochure PDF URL was resolved)**

Use the same pdfplumber check as Task 3 Step 3 against the brochure PDF URL. Document the result.

---

### Task 5: Build Side-by-Side Program Name Comparison

**Files:**
- No changes. Analysis only.

- [ ] **Step 1: List programs from the HUST program listing**

Use the fact list from Task 2 Step 2 (already in hand). Write them in this format:

```
HUST PROGRAM LISTING (2026)
- Khoa học Máy tính (IT1) — quota: <N>
- Kỹ thuật Máy tính (IT2) — quota: <N>
- Công nghệ Thông tin (IT-E10) — quota: <N>
- Kỹ thuật Điện tử - Viễn thông (ET1) — quota: <N>
- Kỹ thuật Cơ điện tử (ME2) — quota: <N>
- (continue for all programs visible)
```

The fact list from Task 2 Step 2 should expose ≥30 programs; capture them all.

- [ ] **Step 2: List programs from the chosen Source #2 PDF**

For the PDF chosen in Task 3 or Task 4 (proposal or brochure), download it and find the HUST 2026 quota table. List every program in the format:

```
HUST PDF SOURCE #2 (2026)
- Khoa học máy tính — quota: <N>  (method: <if PDF breaks by method, capture it>)
- Kỹ thuật máy tính — quota: <N>
- Công nghệ thông tin — quota: <N>
- (continue)
```

**Critical observation to record:** is the PDF quota a single program total per row, or does the PDF break the program into multiple rows by admission method? This decision drives the semantic-measurement check in Step 4.

- [ ] **Step 3: Map names across sources**

For each program that appears in both lists, write a side-by-side comparison:

```
CROSS-SOURCE PROGRAM NAME MAPPING — HUST

| Listing program (code)        | PDF program                     | Quota listing | Quota PDF | Diverges? |
|-------------------------------|---------------------------------|--------------:|----------:|-----------|
| Khoa học Máy tính (IT1)       | Khoa học máy tính               |       150     |    120    | YES       |
| Kỹ thuật Máy tính (IT2)       | Kỹ thuật máy tính               |       100     |    100    | NO        |
| Công nghệ Thông tin (IT-E10)  | Công nghệ thông tin             |       200     |    180    | YES       |
```

This table is the core pre-flight artifact. You need **≥ 3 rows with "YES" in the Diverges column** to satisfy the spec's stated target. If fewer than 3, the spec's per-school target falls back to ≥1 (still acceptable per the spec's bail-out language).

- [ ] **Step 4: Semantic-measurement check (the VNU-UET trap)**

For each diverging pair, ask: **are the two numbers comparing the same thing?**

- If the listing's `Chỉ tiêu tuyển sinh: 150` is "total program quota across all admission methods" and the PDF's `120` is "quota for one specific admission method", the two numbers are not comparable — this is the apples-to-oranges trap that caused commit `6b56301` for VNU-UET.
- Acceptable comparisons: **both** sources report the program total, OR **both** report method-level quota for the same method.
- If one source breaks by method and the other doesn't, you must either (a) sum the per-method quotas in the PDF to compare against the listing's total, or (b) choose only the program-total row from the PDF if present.

Document the semantic-measurement decision explicitly in the findings file. If you can't honestly establish a like-for-like comparison for ≥1 program, this source pair fails pre-flight. Try the other Source #2 candidate (brochure if you tried proposal, or vice versa) before declaring an abort.

- [ ] **Step 5: Evaluate bail-outs**

After completing the table and the semantic check:

**Both Source #2 candidates fail (no PDF found / both unparseable):** Look for a different official HUST channel — for example, a 2026 admission announcement article on `ts.hust.edu.vn` containing per-program quotas in HTML text. Search the news listings (`/b/thong-tin-chung`, `/b/xet-tuyen-tai-nang`). If no third candidate is viable, escalate; do not synthesize a second source.

**Semantic-measurement mismatch persists across both PDF candidates:** Halt. Per the spec, do not proceed by treating asymmetric measurements as a conflict.

**Program name alignment ambiguous** (cannot decide whether "Công nghệ Thông tin (IT-E10)" on the listing equals "Công nghệ thông tin" on the PDF — for instance, if the listing has separate IT-E10 and IT-E7 entries but the PDF lumps them): document the ambiguity and decide one of: (a) include only programs with unambiguous alignment, (b) swap PDF candidate, (c) escalate.

---

### Task 6: Fill Pre-Flight Checklist and Write Findings Document

**Files:**
- Create: `docs/ingestion/hust-preflight-findings.md`

- [ ] **Step 1: Verify the five pre-flight checklist items**

Mark each PASS or FAIL with evidence (each item from spec `2026-05-26-hust-ingestion-design.md` Step 2):

```
[ ] Both sources reachable without auth — <evidence: HTTP 200 ×3 for source #1, HTTP 200 for source #2 PDF>
[ ] PDF source is text-extractable — <evidence: "pdfplumber extracted readable Vietnamese on pages X-Y">
[ ] ≥3 programs with distinct quota across sources — <evidence: see mapping table, N diverging rows>
[ ] Program name alignment unambiguous — <evidence: mapping table; ambiguous cases listed and resolved>
[ ] Both sources publish the same semantic measurement — <evidence: both report program totals> OR <bail-out invoked>
```

If all five PASS, proceed. If any FAIL after exhausting candidates, document the bail-out and escalate before proceeding.

- [ ] **Step 2: Write the findings document**

Create `docs/ingestion/hust-preflight-findings.md` with this structure (mirror the VNU-UET findings file):

```markdown
# HUST Pre-Flight Findings — 2026

**Date:** 2026-05-26
**Outcome:** PASS / PASS_WITH_CAVEATS / ABORT

## Sources Confirmed

| Source | URL | Source type | Trust | Reachability | Evidence |
| --- | --- | --- | --- | --- | --- |
| HUST program listing | https://ts.hust.edu.vn/training-cate/nganh-dao-tao-dai-hoc | program_listing | 5 | PASS | HTTP 200 ×3, hust_programs parser produced N facts |
| HUST 2026 proposal PDF | <PDF URL discovered in Task 3> | admission_proposal | 5 | PASS / FAIL | <evidence> |
| HUST brochure PDF (fallback) | <PDF URL discovered in Task 4> | brochure | 3 | PASS / FAIL | <evidence — used if proposal failed> |

## Checklist Results

| Check | Result | Evidence |
| --- | --- | --- |
| Both sources reachable without auth | PASS | <details> |
| PDF text-extractable | PASS | <pdfplumber extraction page samples> |
| ≥3 programs with distinct quota across sources | PASS | <N diverging tuples found> |
| Program name alignment unambiguous | PASS / PASS_WITH_CAVEATS | <details, plus list of any caveats> |
| Same semantic measurement on both sources | PASS | <both are program totals, or both are method-level> |
| (Prerequisite) DB writer conflict key | PASS | <Task 1 evidence> |

## Program Name Mapping Table

| Listing program (code) | PDF program | Quota listing | Quota PDF | Diverges? |
|---|---|---:|---:|---|
| ... | ... | ... | ... | YES / NO |

## HTML / PDF Structure Notes (for Plans 03–04)

HUST program listing:
- Parser: existing `HustProgramParser` (`parser_profile="hust_programs"`)
- admission_method_raw observed: <list — likely None for most facts>
- Quota label: `Chỉ tiêu tuyển sinh: <N>`

HUST 2026 PDF (proposal or brochure):
- Section heading for the quota table: `<page N>`
- Table columns observed: `<column names>`
- pdfplumber extraction quality: GOOD / PARTIAL / POOR
- Does PDF break quotas by admission method? YES / NO
- If YES, list method labels seen: `<list>`

## Semantic-Measurement Decision

- Listing measures: <program total / method-specific>
- PDF measures: <program total / method-specific>
- Decision: compare on `<like-for-like axis>` because <reason>
- Bail-out invoked: <yes/no, describe>

## Bail-Outs Applied

<describe any bail-outs, or "none">

## Pre-Flight Verdict

PROCEED / PROCEED_WITH_CAVEATS / ABORT
```

The verdict line must be the final line — Plan 02 checks for it.

- [ ] **Step 3: Commit the findings document**

```powershell
git add docs/ingestion/hust-preflight-findings.md
git commit -m "docs: add HUST 2026 pre-flight findings"
```

---

### Self-Check Before Proceeding to Plan 02

The following must all be true before starting Plan 02:

- `docs/ingestion/hust-preflight-findings.md` is committed with a final "Pre-Flight Verdict: PROCEED" (or PROCEED_WITH_CAVEATS) line
- The findings document contains the exact PDF URL chosen for Source #2 (proposal or brochure)
- The findings document contains the cross-source program name mapping table with ≥1 diverging quota pair (≥3 preferred)
- The findings document explicitly records the semantic-measurement decision (both totals, both method-level, or like-for-like reasoning)
- The `canonical_admission_records` table has the `source_url` column and the new `ON CONFLICT` target
