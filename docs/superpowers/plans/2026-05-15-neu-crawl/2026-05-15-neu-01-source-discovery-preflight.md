# NEU Source Discovery & Pre-Flight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover and manually verify NEU's 2026 admission sources, confirm both sources are parseable with differing quota values, and document findings before any code is written.

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

Expected: The output includes a `source_url` column and a unique constraint on `(school_id, admission_year, program_id, admission_method, source_url)`. The exact constraint name comes from migration `010_canonical_records_per_source.sql`.

If the `source_url` column does **not** appear, stop here. Apply spec `2026-05-15-canonical-records-per-source-design.md` migration before continuing.

- [ ] **Step 2: Confirm db_writer uses the new ON CONFLICT target**

Run:
```
grep -n "ON CONFLICT" ingestion/storage/db_writer.py
```

Expected: At least one `ON CONFLICT` clause that includes `source_url` in its target columns. If it targets only `(school_id, admission_year, program_id, admission_method)`, the migration is not yet integrated — stop and complete Spec A first.

---

### Task 2: Inspect NEU Admission Homepage

**Files:**
- No changes. Observation only.

- [ ] **Step 1: Open the NEU admission homepage**

Navigate to: `https://tuyensinh.neu.edu.vn/`

If that URL 404s or shows no 2026 data, try:
- `https://neu.edu.vn/tuyen-sinh/`
- `https://neu.edu.vn/tuyen-sinh-2026/`

Document the exact URL that loads and shows 2026 admission program data.

Check:
- Does the page load without authentication?
- Is there a list or table of programs with quota numbers (`chỉ tiêu`)?
- Are admission methods (`phương thức xét tuyển`) mentioned per program or in a separate section?
- What does the HTML structure look like? (Right-click → Inspect → look for repeating `<tr>`, `<div class="...">`, or `<table>` containers around program info.)

Note down:
- Working URL (exact, after any redirects)
- CSS class of the main program container (e.g., `div.chuong-trinh`, `table.admissions-table`, `tr` inside a specific `table`)
- Example program name as it appears on the page (exact Vietnamese text, e.g. "Tài chính - Ngân hàng")
- Example quota number and the HTML element it lives in
- Whether quota numbers are JavaScript-rendered (quota missing from initial `curl` response)

- [ ] **Step 2: Check reachability without rate limiting**

Run the following three times within 30 seconds to confirm no rate limiting:
```
curl -s -o /dev/null -w "%{http_code}" https://tuyensinh.neu.edu.vn/
```

Expected: `200` each time. If you get `429` or `503`, document this — the source may need `fetch_strategy: "browser"` rather than `"http"`.

- [ ] **Step 3: Confirm quota data is in the static HTML response (not JS-rendered)**

Run:
```
curl -s "https://tuyensinh.neu.edu.vn/" | grep -i "chỉ tiêu\|chi tieu\|quota" | head -20
```

If nothing appears but the browser shows quota numbers, the page uses JavaScript rendering. Document this as a critical risk for Plan 03 — the default HTTP fetcher will return empty quota tables, requiring escalation before parser work begins.

---

### Task 3: Inspect NEU 2026 Admission Proposal PDF

**Files:**
- No changes. Observation only.

- [ ] **Step 1: Find the 2026 NEU proposal PDF**

Navigate to `https://tuyensinh.neu.edu.vn/` and look for the 2026 admission proposal ("Đề án tuyển sinh 2026", "Thông báo tuyển sinh 2026", or "Quyết định tuyển sinh 2026"). It may also be published at:
- `https://neu.edu.vn/` under a news/announcement section
- NEU's official document portal

If no direct link is visible on the homepage, search:
```
site:neu.edu.vn "đề án tuyển sinh 2026" filetype:pdf
```

Document the exact PDF URL (needed in Plan 02 registry entries).

If no PDF is found, check whether NEU publishes a structured HTML announcement page instead. Note this as a bail-out: use the HTML announcement as the second source.

- [ ] **Step 2: Verify the PDF is text-extractable, not a scan**

Download the PDF:
```
curl -L -o /tmp/neu_proposal_2026.pdf "<PDF_URL>"
```

Open `/tmp/neu_proposal_2026.pdf` in a PDF reader (Evince, Adobe Reader, or browser).

Navigate to a quota table for NEU programs. Try to select text from a number in the quota column. If you can select and copy text → text-extractable. If the cursor behaves like you are hovering over an image → scanned.

If scanned: document this as bail-out — switch the second source to NEU's HTML announcement page or a MOET aggregate page. Mark the PDF source as excluded.

- [ ] **Step 3: Test pdfplumber text extraction on the NEU PDF**

Run:
```python
python - <<'EOF'
import pdfplumber
with pdfplumber.open("/tmp/neu_proposal_2026.pdf") as pdf:
    for i, page in enumerate(pdf.pages[:5]):
        text = page.extract_text()
        print(f"--- Page {i+1} ---")
        print(text[:600] if text else "(empty)")
EOF
```

Expected: Pages contain readable Vietnamese text including program names (e.g., "Tài chính - Ngân hàng", "Kế toán", "Marketing") and numeric quota values. If pages return `(empty)` or garbled bytes, the default PDF parser will likely fail — document as a risk for Plan 03.

---

### Task 4: Build Side-by-Side Program Name Comparison

**Files:**
- No changes. Analysis only.

- [ ] **Step 1: List programs from the NEU admission homepage**

From your Task 2 inspection, note all programs visible on the page along with their 2026 quota. Write them in this format:

```
NEU HOMEPAGE PROGRAMS (2026)
- Tài chính - Ngân hàng — quota: <N>
- Kế toán — quota: <N>
- Kinh doanh quốc tế — quota: <N>
- Marketing — quota: <N>
- Khoa học máy tính / Hệ thống thông tin quản lý — quota: <N>
- Logistics và Quản lý chuỗi cung ứng — quota: <N>
- (add all visible)
```

- [ ] **Step 2: List programs from the NEU proposal PDF**

From the PDF (Task 3), find the program quota table. It is typically headed "Chỉ tiêu tuyển sinh 2026" or similar. List all programs with their 2026 quota:

```
NEU PROPOSAL PDF (2026)
- Tài chính - Ngân hàng — quota: <N>
- Kế toán — quota: <N>
- Kinh doanh quốc tế — quota: <N>
- Marketing — quota: <N>
- (add all visible)
```

- [ ] **Step 3: Map names across sources**

For each program that appears in both lists, write a side-by-side comparison:

```
CROSS-SOURCE PROGRAM NAME MAPPING
| NEU Homepage name                  | PDF name                           | Quota Homepage | Quota PDF | Diverges? |
|------------------------------------|------------------------------------|----------------|-----------|-----------|
| Tài chính - Ngân hàng              | Tài chính - Ngân hàng              | 600            | 550        | YES       |
| Kế toán                            | Kế toán                            | 400            | 380        | YES       |
| Kinh doanh quốc tế                 | Kinh doanh quốc tế                 | 300            | 250        | YES       |
```

This table is the core pre-flight artifact. You need **≥ 3 rows with "YES" in the Diverges column** to continue confidently, but ≥ 1 is the hard acceptance gate.

- [ ] **Step 4: Evaluate bail-outs**

After completing the table:

**If fewer than 3 rows diverge on quota:** Re-check whether the PDF covers admission methods (`phương thức`) separately — if so, use program+method as the comparison unit. If still < 3 conflicts, document the reduction; ≥1 conflict-bearing tuple is the acceptance gate.

**If program name alignment is ambiguous** (cannot determine with certainty that a PDF name equals a homepage name): document this and swap the source pair before proceeding.

**If the PDF is useless:** exclude it. Find an HTML replacement: NEU's news/announcement HTML page announcing 2026 quotas, or a MOET aggregate page for NEU.

**If both sources agree on all quota numbers:** escalate to project owner. Do not proceed with parser work. Options: (a) find a third NEU source with different numbers, (b) accept NEU as non-conflict-bearing coverage, (c) replace NEU with FTU.

---

### Task 5: Fill Pre-Flight Checklist and Write Findings Document

**Files:**
- Create: `docs/ingestion/neu-preflight-findings.md`

- [ ] **Step 1: Verify the four pre-flight checklist items**

Go through each item and mark PASS or FAIL with evidence:

```
[ ] Both sources reachable without auth — <evidence>
[ ] PDF is text-extractable (or replacement HTML is quota-bearing) — <evidence>
[ ] ≥3 programs with distinct quota across sources — <evidence: mapping table>
[ ] Program name alignment unambiguous — <evidence: mapping table row by row>
```

If all four PASS, proceed. If any FAIL, document the bail-out action taken.

- [ ] **Step 2: Write the findings document**

Create `docs/ingestion/neu-preflight-findings.md` with this structure:

```markdown
# NEU Pre-Flight Findings — 2026

**Date:** 2026-05-15
**Outcome:** PASS / BAIL-OUT (circle one)

## Sources Confirmed

| Source | URL | Type | Trust | Reachable |
|--------|-----|------|-------|-----------|
| NEU admission homepage | https://tuyensinh.neu.edu.vn/ | admission_homepage | 4 | YES |
| NEU proposal PDF | <exact PDF URL> | admission_proposal | 5 | YES |

## Checklist Results

- [x] Both sources reachable without auth
- [x] PDF is text-extractable (selected text on page <N>)
- [x] ≥3 programs with distinct quota: <N> found
- [x] Program name alignment unambiguous

## Program Name Mapping Table

| NEU Homepage name | PDF name | Quota Homepage | Quota PDF | Diverges? |
|...|...|...|...|...|

## HTML Structure Notes (for Plan 03 parser work)

NEU Homepage:
- Program container selector: `<css selector found in Task 2>`
- Quota label: `<text pattern before quota number>`
- Method labels: `<text patterns seen, e.g., "Phương thức 1: xét điểm THPT">`
- JS-rendered: YES / NO

NEU Proposal PDF:
- Program quota table starts at page: <N>
- Table columns order: program_name | code | method | quota | ...
- pdfplumber extraction quality: GOOD / PARTIAL / POOR

## Bail-Outs Applied (if any)

<describe any bail-outs or "none">
```

- [ ] **Step 3: Commit the findings document**

```bash
git add docs/ingestion/neu-preflight-findings.md
git commit -m "docs: add NEU 2026 pre-flight findings"
```

---

### Self-Check Before Proceeding to Plan 02

The following must all be true before starting Plan 02:

- `docs/ingestion/neu-preflight-findings.md` is committed with Outcome = PASS
- The findings document contains the exact PDF URL (or the replacement HTML URL if PDF was excluded)
- The findings document contains the exact NEU homepage URL
- The findings document contains the cross-source program name mapping table with ≥1 diverging quota pair (≥3 preferred)
- The `canonical_admission_records` table has the `source_url` column and the new `ON CONFLICT` target
