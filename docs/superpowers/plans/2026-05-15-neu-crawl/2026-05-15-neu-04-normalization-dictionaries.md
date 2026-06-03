# NEU Normalization Dictionary Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add NEU-specific program entries and method entries to the normalization dictionaries so that every conflict-bearing program-method tuple resolves to a non-null `program_id`, non-null `program_name_canonical`, and non-null `admission_method` that matches across both NEU sources.

**Architecture:** Two JSON dictionary files are edited: `programs.json` (add a `"neu"` section) and `methods.json` (add a `"neu"` section). No Python changes. The normalizer loads school-specific entries by `school_id`; since sources use `school_id="neu"`, both files need that key.

**Tech Stack:** JSON, Python (normalization test script).

**Prerequisite:** Plan 03 complete — parser returns raw facts with real program names and method text for both NEU sources.

---

### Task 1: Understand What the Parser Currently Produces

**Files:**
- Read only. No changes yet.

- [ ] **Step 1: Collect raw program names and method text from parser output**

Run the diagnostic script from Plan 03 and capture output:

```
python scripts/test_neu_parser.py 2>&1 | tee /tmp/neu_raw_facts.txt
```

From `/tmp/neu_raw_facts.txt`, write down all unique values of:
- `program_name` across all facts from both sources
- `admission_method_raw` across all facts from both sources

Example (your actual values will differ based on what the parser extracted):
```
RAW PROGRAM NAMES (NEU homepage):
  "Tài chính - Ngân hàng"
  "Kế toán"
  "Kinh doanh quốc tế"
  "Marketing"
  "Khoa học máy tính"
  "Logistics và Quản lý chuỗi cung ứng"

RAW PROGRAM NAMES (NEU proposal PDF):
  "Tài chính - Ngân hàng"
  "Kế toán"
  "Kinh doanh quốc tế"
  "Marketing"
  "Khoa học máy tính"

RAW METHOD TEXT:
  "xét điểm thi TN THPT"
  "xét học bạ THPT"
  "xét tuyển kết hợp"
  "tuyển thẳng"
  (may be None if parser did not extract method)
```

- [ ] **Step 2: Identify which programs already resolve via `_shared` entries**

Run:

```python
python - <<'EOF'
import sys; sys.path.insert(0, ".")
from ingestion.normalization.program_mapper import map_program

# Replace with the actual names from your Task 1 Step 1 output
test_names = [
    "Tài chính - Ngân hàng",
    "Kế toán",
    "Kinh doanh quốc tế",
    "Marketing",
    "Khoa học máy tính",
    "Logistics và Quản lý chuỗi cung ứng",
    "Hệ thống thông tin quản lý",
    "Quản trị kinh doanh",
    "Kinh tế",
    # add all names from your raw output above
]

for name in test_names:
    pid, canonical = map_program(name, school_id="neu")
    status = "OK" if pid else "MISSING"
    print(f"  [{status}] {name!r} -> pid={pid!r}, canonical={canonical!r}")
EOF
```

Note every name that prints `[MISSING]` — those need a new `neu` dictionary entry or an alias added to an existing `_shared` entry.

---

### Task 2: Update `programs.json` — Add NEU Section

**Files:**
- Modify: `ingestion/normalization/dictionaries/programs.json`

- [ ] **Step 1: Write a test that asserts all conflict-bearing programs resolve**

Create `scripts/verify_neu_normalization.py`:

```python
"""
Assert that NEU program names (from both sources) normalize to
the same program_id. This is the invariant that makes the conflict
signal land on the same canonical row pair.
"""
import sys
sys.path.insert(0, ".")
from ingestion.normalization.program_mapper import map_program
from ingestion.normalization.method_mapper import map_method

# Replace these with the actual names from Task 1 Step 1.
# For each conflict-bearing program, list its name from EACH source.
PROGRAM_PAIRS = [
    ("Tài chính - Ngân hàng",           "Tài chính - Ngân hàng"),
    ("Kế toán",                          "Kế toán"),
    ("Kinh doanh quốc tế",              "Kinh doanh quốc tế"),
    ("Marketing",                        "Marketing"),
    ("Khoa học máy tính",               "Khoa học máy tính"),
]

KNOWN_METHOD_CODES = {
    "thpt_score", "school_record", "talent_admission",
    "combined", "competency_test",
}

METHOD_SAMPLES = [
    "xét điểm thi TN THPT",
    "xét học bạ THPT",
    "xét tuyển kết hợp",
    "tuyển thẳng",
]

print("=== Program mapping ===")
all_ok = True
for homepage_name, pdf_name in PROGRAM_PAIRS:
    pid_h, canon_h = map_program(homepage_name, school_id="neu")
    pid_p, canon_p = map_program(pdf_name, school_id="neu")
    match = pid_h and pid_h == pid_p
    status = "MATCH" if match else "MISMATCH"
    if not match:
        all_ok = False
    print(f"  [{status}]")
    print(f"    Homepage: {homepage_name!r} -> pid={pid_h!r}")
    print(f"    PDF     : {pdf_name!r} -> pid={pid_p!r}")

print("\n=== Method mapping ===")
for raw in METHOD_SAMPLES:
    result = map_method(raw, school_id="neu")
    mapped = result in KNOWN_METHOD_CODES
    status = "OK" if mapped else "UNMAPPED"
    if not mapped:
        all_ok = False
    print(f"  [{status}] {raw!r} -> {result!r}")

if all_ok:
    print("\nPASS")
else:
    print("\nFAIL — fix the dictionaries above")
    sys.exit(1)
```

- [ ] **Step 2: Run to confirm it fails before dictionary edits**

```
python scripts/verify_neu_normalization.py
```

Expected: Several `[MISMATCH]` or `[UNMAPPED]` lines and `FAIL` at the end. (If it passes already, some NEU names happened to match shared entries — still proceed to verify coverage for all conflict-bearing programs.)

- [ ] **Step 3: Update `PROGRAM_PAIRS` with your actual names from Task 1**

Open `scripts/verify_neu_normalization.py`. Replace the `PROGRAM_PAIRS` list with the actual raw program names you collected in Task 1 Step 1. Include every program that appears in both sources (the conflict-bearing set). Replace `METHOD_SAMPLES` with the actual method strings returned by the parser.

- [ ] **Step 4: Add the `"neu"` section to `programs.json`**

Open `ingestion/normalization/dictionaries/programs.json`. After the last existing school section and before the final `}` of the file, add a `"neu"` section.

NEU is an economics and business school. Add only programs that showed `[MISSING]` in Task 1 Step 2 — do not duplicate entries already covered by `_shared`:

```json
  "neu": {
    "finance_banking_neu": {
      "canonical_name": "Tài chính - Ngân hàng",
      "aliases": [
        "Tài chính - Ngân hàng",
        "Tài chính Ngân hàng",
        "Finance - Banking",
        "Finance and Banking",
        "Ngành Tài chính - Ngân hàng"
      ],
      "field": "economics"
    },
    "accounting_neu": {
      "canonical_name": "Kế toán",
      "aliases": [
        "Kế toán",
        "Kế toán - Kiểm toán",
        "Accounting",
        "Accounting and Auditing",
        "Ngành Kế toán"
      ],
      "field": "economics"
    },
    "international_business_neu": {
      "canonical_name": "Kinh doanh quốc tế",
      "aliases": [
        "Kinh doanh quốc tế",
        "International Business",
        "KDQT",
        "Ngành Kinh doanh quốc tế"
      ],
      "field": "business"
    },
    "marketing_neu": {
      "canonical_name": "Marketing",
      "aliases": [
        "Marketing",
        "Ngành Marketing",
        "Quản trị Marketing",
        "Marketing và Quản lý"
      ],
      "field": "business"
    },
    "logistics_supply_chain_neu": {
      "canonical_name": "Logistics và Quản lý chuỗi cung ứng",
      "aliases": [
        "Logistics và Quản lý chuỗi cung ứng",
        "Logistics",
        "Quản lý chuỗi cung ứng",
        "Logistics and Supply Chain Management",
        "Logistics & SCM"
      ],
      "field": "business"
    },
    "management_information_systems_neu": {
      "canonical_name": "Hệ thống thông tin quản lý",
      "aliases": [
        "Hệ thống thông tin quản lý",
        "Management Information Systems",
        "MIS",
        "Thông tin quản lý",
        "Hệ thống thông tin"
      ],
      "field": "technology"
    },
    "business_administration_neu": {
      "canonical_name": "Quản trị kinh doanh",
      "aliases": [
        "Quản trị kinh doanh",
        "Business Administration",
        "Quản trị Kinh doanh",
        "QTKD",
        "Business Management"
      ],
      "field": "business"
    },
    "economics_neu": {
      "canonical_name": "Kinh tế",
      "aliases": [
        "Kinh tế",
        "Economics",
        "Ngành Kinh tế",
        "Kinh tế học"
      ],
      "field": "economics"
    }
  }
```

**Important — only add entries for programs that showed `[MISSING]` in Task 1 Step 2.** If "Khoa học máy tính" already resolves via the `_shared.computer_science` entry, do NOT add a `neu.computer_science_neu` entry — that creates a duplicate resolution path without helping. Only add entries for programs with no `_shared` match.

The aliases for each entry must include the exact string returned by `fact.program_name` for each source.

- [ ] **Step 5: Confirm JSON is valid**

```
python -c "import json; d = json.load(open('ingestion/normalization/dictionaries/programs.json')); print('neu programs:', list(d.get('neu', {}).keys()))"
```

Expected: Lists the program IDs you added.

---

### Task 3: Update `methods.json` — Add NEU Section

**Files:**
- Modify: `ingestion/normalization/dictionaries/methods.json`

NEU is an economics/business school and uses different admission methods compared to HUST and VNU-UET. Key NEU-specific methods include combined admission (with language certificates like IELTS/SAT) and school-record-based admission.

- [ ] **Step 1: Check whether a `"neu"` section already exists in methods.json**

```python
python -c "import json; d = json.load(open('ingestion/normalization/dictionaries/methods.json')); print('Existing keys:', list(d.keys()))"
```

If a `"neu"` key exists, review its contents and skip to Step 3. If not, proceed to Step 2.

- [ ] **Step 2: Add the `"neu"` section to `methods.json`**

Open `ingestion/normalization/dictionaries/methods.json`. After the last existing school section and before the final `}` of the file, add:

```json
  "neu": {
    "combined": {
      "canonical_name": "Xét tuyển kết hợp",
      "aliases": [
        "xét tuyển kết hợp",
        "kết hợp chứng chỉ quốc tế",
        "xét tuyển ưu tiên IELTS",
        "xét tuyển ưu tiên SAT",
        "ưu tiên xét tuyển IELTS/SAT",
        "xét tuyển kết hợp chứng chỉ",
        "kết hợp IELTS",
        "phương thức kết hợp"
      ]
    },
    "school_record": {
      "canonical_name": "Xét học bạ THPT",
      "aliases": [
        "xét học bạ THPT",
        "xét tuyển theo kết quả học bạ",
        "học bạ THPT",
        "kết quả học tập THPT",
        "xét tuyển học bạ",
        "xét học bạ"
      ]
    },
    "talent_admission": {
      "canonical_name": "Xét tuyển tài năng",
      "aliases": [
        "tuyển thẳng",
        "xét tuyển tài năng",
        "xét tuyển thẳng",
        "tuyển thẳng theo quy chế Bộ GD&ĐT",
        "miễn thi"
      ]
    }
  }
```

Only add methods that actually appear in your Task 1 Step 1 output. Remove any entries for method strings that didn't appear in the parser output.

- [ ] **Step 3: Add missing method aliases observed in Task 1 Step 1**

From your `METHOD_SAMPLES` in the verification script, check which raw strings are still `[UNMAPPED]` after Step 2. For each, add the exact raw string as an alias under the appropriate method code in the `"neu"` section.

Example: if `"xét tuyển ưu tiên IELTS/SAT"` is unmapped and should map to `combined`, add it to the `combined.aliases` list.

- [ ] **Step 4: Confirm JSON is valid**

```
python -c "import json; d = json.load(open('ingestion/normalization/dictionaries/methods.json')); print('neu methods:', list(d.get('neu', {}).keys()))"
```

Expected: Lists `combined`, `school_record`, `talent_admission` (plus any additional ones you added).

---

### Task 4: Invalidate Normalization Cache and Verify

The normalizer uses a module-level cache dict populated at import time. After editing the JSON files, you must run the verification in a **fresh Python process** to avoid using stale cached data.

- [ ] **Step 1: Run the verification script in a fresh process**

```
python scripts/verify_neu_normalization.py
```

Expected: All `[MATCH]` and `[OK]` lines, then `PASS`.

If a program pair still shows `[MISMATCH]`:
- Both names must resolve to the **same** `program_id`. Check that the alias list for that entry in `programs.json` covers the exact raw string returned by the parser for that source.
- Debug interactively:
  ```python
  python -c "import sys; sys.path.insert(0,''); from ingestion.normalization.program_mapper import map_program; print(map_program('Tài chính - Ngân hàng', school_id='neu'))"
  ```

- [ ] **Step 2: Run the full normalization path on actual facts**

```python
python - <<'EOF'
import sys; sys.path.insert(0, ".")
from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.fetchers.fetch_dispatcher import dispatch_fetch
from ingestion.router.document_router import route_document
from ingestion.parsers.parser_dispatcher import dispatch_parser
from ingestion.extractors.admission_extractor import extract_admission_facts
from ingestion.normalization.normalizer import normalize_facts

pipeline = IngestionPipeline()
sources = pipeline.registry.get_sources_by_school("neu")

for source in sources:
    print(f"\nSource: {source.source_id}")
    fetch = dispatch_fetch(source)
    doc_type = route_document(fetch)
    parsed = dispatch_parser(fetch, doc_type, source)
    if isinstance(parsed, list):
        facts = parsed
    else:
        facts = extract_admission_facts(parsed, source)

    records = normalize_facts(facts, source)
    print(f"  {len(facts)} facts -> {len(records)} normalized records")
    for r in records[:3]:
        pid = r.program_id or "NONE"
        pname = r.program_name_canonical or "NONE"
        method = r.admission_method or "NONE"
        quota = r.quota.value if r.quota else "NONE"
        print(f"  program_id={pid!r}  canonical={pname!r}  method={method!r}  quota={quota}")
EOF
```

Acceptance criteria:
- `program_id` is non-null for all facts from conflict-bearing programs
- `program_name_canonical` is the same string for the same logical program across both sources
- `admission_method` is non-null for at least some records (THPT score, school record, or combined)

If `program_id="NONE"` for any conflict-bearing program, the alias is missing — add it to `programs.json` and re-run in a fresh process.

---

### Task 5: Commit Dictionary Updates

- [ ] **Step 1: Run all existing tests**

```
python -m pytest tests/ingestion/ -v
```

Expected: All pass. Dictionary changes don't break any existing tests.

- [ ] **Step 2: Commit**

```bash
git add ingestion/normalization/dictionaries/programs.json \
        ingestion/normalization/dictionaries/methods.json \
        scripts/verify_neu_normalization.py
git commit -m "feat: add NEU program and method normalization dictionary entries"
```

---

### Self-Check Before Proceeding to Plan 05

- `python scripts/verify_neu_normalization.py` prints PASS
- All conflict-bearing program pairs map to the **same** `program_id` from both sources
- `admission_method` is non-null for at least the THPT score and one NEU-specific method
- All existing tests pass
