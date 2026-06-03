# VNU-UET Source Discovery & Pre-Flight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover and manually verify VNU-UET's 2026 admission sources, confirm both sources are parseable with differing quota values, and document findings before any code is written.

**Architecture:** Pure investigation — browse live URLs, extract text from the PDF, compare program names side-by-side, then commit a findings document. No source-registry or parser changes in this plan; those follow in Plans 02–05.

**Tech Stack:** Browser / curl for URL inspection, a PDF reader for text extractability check, psql for prerequisite verification, Markdown for findings document.

---

### Task 1: Verify Prerequisite — Canonical Records Migration Applied

**Files:**
- No file changes. This is a database inspection step.

- [ ] **Step 1: Connect to psql and check the uniqueness constraint**

Run:
```
psql -U <DB_USER> -d <DB_NAME> -c "\d canonical_admission_records"
```

Expected: The output includes a unique constraint on `(school_id, admission_year, program_id, admission_method, source_url)` **or** a `source_url` column is present at all. The exact constraint name depends on migration `010_canonical_records_per_source.sql`.

If the `source_url` column does **not** appear in `\d canonical_admission_records`, stop here. Apply spec `2026-05-15-canonical-records-per-source-design.md` migration before continuing.

- [ ] **Step 2: Confirm db_writer uses the new ON CONFLICT target**

Run:
```
grep -n "ON CONFLICT" ingestion/storage/db_writer.py
```

Expected: At least one `ON CONFLICT` clause that includes `source_url` in its target columns. If it targets only `(school_id, admission_year, program_id, admission_method)`, the migration is not yet integrated — stop and complete Spec A first.

---

### Task 2: Inspect UET Admission Homepage

**Files:**
- No changes. Observation only.

- [ ] **Step 1: Open the UET admission homepage**

Navigate to: `https://uet.vnu.edu.vn/tuyen-sinh-dai-hoc/`

If that URL 404s, try `https://uet.vnu.edu.vn/tuyen-sinh/`. Document the exact URL that loads.

Check:
- Does the page load without authentication?
- Is there a list or table of programs with quota numbers?
- Are admission methods mentioned per program?
- What does the HTML structure look like? (Right-click → Inspect → look for repeating `<tr>`, `<div class="...">` containers around program info.)

Note down:
- Working URL
- CSS class of the main program container (e.g., `div.chuong-trinh`, `table.ts-table`, `tr` inside a specific `table`)
- Example program name as it appears on the page (exact Vietnamese text)
- Example quota number and the HTML element it lives in

- [ ] **Step 2: Check reachability without rate limiting**

Run the following three times within 30 seconds to confirm no rate limiting:
```
curl -s -o /dev/null -w "%{http_code}" https://uet.vnu.edu.vn/tuyen-sinh-dai-hoc/
```

Expected: `200` each time. If you get `429` or `503`, document this — the source may need `fetch_strategy: "browser"` instead of `"http"`.

---

### Task 3: Inspect ĐHQGHN Admission Proposal PDF

**Files:**
- No changes. Observation only.

- [ ] **Step 1: Find the 2026 ĐHQGHN proposal PDF**

Navigate to: `https://tuyensinh.vnu.edu.vn/` and look for the 2026 admission proposal ("Đề án tuyển sinh 2026"). It is also linked from `https://www.vnu.edu.vn/` under the tuyển sinh section.

If neither URL yields the PDF, search: `site:vnu.edu.vn "đề án tuyển sinh 2026" filetype:pdf`

Document the exact PDF URL (it will be needed in Plan 02).

- [ ] **Step 2: Verify the PDF is text-extractable, not a scan**

Download the PDF:
```
curl -L -o /tmp/vnuhn_proposal_2026.pdf "<PDF_URL>"
```

Open `/tmp/vnuhn_proposal_2026.pdf` in a PDF reader (Evince, Adobe Reader, or browser).

Navigate to a quota table for VNU-UET programs. Try to select text from a number in the quota column. If you can select and copy text → text-extractable. If the cursor behaves like you're hovering over an image → scanned.

If scanned: document the bail-out, mark this source as excluded, and search for an HTML alternative (VNU-UET press release, official HTML version of the announcement).

- [ ] **Step 3: Test pdfplumber/pymupdf text extraction**

Run:
```python
python - <<'EOF'
import pdfplumber
with pdfplumber.open("/tmp/vnuhn_proposal_2026.pdf") as pdf:
    for i, page in enumerate(pdf.pages[:5]):
        text = page.extract_text()
        print(f"--- Page {i+1} ---")
        print(text[:500] if text else "(empty)")
EOF
```

Expected: Pages contain readable Vietnamese text including program names and numbers. If pages return `(empty)` or garbled bytes, the default PDF parser will likely fail — document this as a risk for Plan 03.

---

### Task 4: Build Side-by-Side Program Name Comparison

**Files:**
- No changes. Analysis only.

- [ ] **Step 1: List programs from the UET homepage**

From your Task 2 inspection, note all programs visible on the UET admission page along with their quota for 2026. Write them in this format:

```
UET HOMEPAGE PROGRAMS (2026)
- Khoa học Máy tính — quota: <N>
- Kỹ thuật Máy tính — quota: <N>
- Công nghệ Thông tin — quota: <N>
- Điện tử Viễn thông — quota: <N>
- Cơ điện tử — quota: <N>
- (add all visible)
```

- [ ] **Step 2: List programs from the ĐHQGHN proposal PDF for VNU-UET**

From the PDF (Task 3), find the VNU-UET section. It is usually headed "Trường Đại học Công nghệ" or "Đại học Công nghệ - ĐHQGHN". List all programs with their 2026 quota:

```
ĐHQGHN PROPOSAL PDF (2026, VNU-UET section)
- Khoa học máy tính — quota: <N>
- Kỹ thuật máy tính — quota: <N>
- Công nghệ thông tin — quota: <N>
- (add all visible)
```

- [ ] **Step 3: Map names across sources**

For each program that appears in both lists, write a side-by-side comparison:

```
CROSS-SOURCE PROGRAM NAME MAPPING
| UET Homepage name              | PDF name                        | Quota UET | Quota PDF | Diverges? |
|--------------------------------|---------------------------------|-----------|-----------|-----------|
| Khoa học Máy tính              | Khoa học máy tính               | 150       | 120       | YES       |
| Kỹ thuật Máy tính              | Kỹ thuật máy tính               | 100       | 90        | YES       |
| Công nghệ Thông tin            | Công nghệ thông tin             | 200       | 180       | YES       |
```

This table is the core pre-flight artifact. You need **≥ 3 rows with "YES" in the Diverges column** to continue.

- [ ] **Step 4: Evaluate bail-outs**

After completing the table:

**If fewer than 3 rows diverge on quota:** Re-check whether the PDF covers admission methods (phương thức) separately from combined quota. If so, use program+method as the comparison unit. If still < 3 conflicts, document the reduction and lower the target to ≥1 conflict-bearing tuple.

**If program name alignment is ambiguous** (cannot determine with certainty that "Khoa học máy tính" on the PDF = "Khoa học Máy tính" on the homepage): document and swap the source pair before proceeding.

**If PDF is useless:** exclude the PDF source. Find an HTML replacement (VNU's tuyển sinh announcement page, or a UET press release with quota data).

---

### Task 5: Fill Pre-Flight Checklist and Write Findings Document

**Files:**
- Create: `docs/ingestion/vnu-uet-preflight-findings.md`

- [ ] **Step 1: Verify the four pre-flight checklist items**

Go through each item and mark PASS or FAIL with evidence:

```
[ ] Both sources reachable without auth — <evidence>
[ ] PDF is text-extractable — <evidence: "selected text from page N, quota table">
[ ] ≥3 programs with distinct quota across sources — <evidence: see mapping table>
[ ] Program name alignment unambiguous — <evidence: mapping table row by row>
```

If all four PASS, proceed. If any FAIL, document the bail-out action taken.

- [ ] **Step 2: Write the findings document**

Create `docs/ingestion/vnu-uet-preflight-findings.md` with this structure:

```markdown
# VNU-UET Pre-Flight Findings — 2026

**Date:** 2026-05-15
**Outcome:** PASS / BAIL-OUT (circle one)

## Sources Confirmed

| Source | URL | Type | Trust | Reachable |
|--------|-----|------|-------|-----------|
| UET admission homepage | https://uet.vnu.edu.vn/tuyen-sinh-dai-hoc/ | admission_homepage | 4 | YES |
| ĐHQGHN proposal PDF | <exact PDF URL> | proposal_pdf | 5 | YES |

## Checklist Results

- [x] Both sources reachable without auth
- [x] PDF is text-extractable (selected text on page <N>)
- [x] ≥3 programs with distinct quota: <N> found
- [x] Program name alignment unambiguous

## Program Name Mapping Table

| UET Homepage name | PDF name | Quota UET | Quota PDF | Diverges? |
|...|...|...|...|...|

## HTML Structure Notes (for Plan 03 parser work)

UET Homepage:
- Program container selector: `<css selector found in Task 2>`
- Quota label: `<text before quota number>`
- Method labels: `<text patterns seen>`

ĐHQGHN PDF:
- VNU-UET section starts at page: <N>
- Table columns order: program_name | code | method | quota | ...
- pdfplumber extraction quality: GOOD / PARTIAL / POOR

## Bail-Outs Applied (if any)

<describe any bail-outs or "none">
```

- [ ] **Step 3: Commit the findings document**

```bash
git add docs/ingestion/vnu-uet-preflight-findings.md
git commit -m "docs: add VNU-UET 2026 pre-flight findings"
```

---

### Self-Check Before Proceeding to Plan 02

The following must all be true before starting Plan 02:

- `docs/ingestion/vnu-uet-preflight-findings.md` is committed with Outcome = PASS
- The findings document contains the exact PDF URL
- The findings document contains the exact UET homepage URL
- The findings document contains the cross-source program name mapping table with ≥1 diverging quota pair (≥3 preferred)
- The `canonical_admission_records` table has the `source_url` column and the new `ON CONFLICT` target
