# VNU-UET Normalization Dictionary Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add VNU-UET-specific program entries and method entries to the normalization dictionaries so that every conflict-bearing program-method tuple resolves to a non-null `program_id`, non-null `program_name_canonical`, and non-null `admission_method` that matches across both sources.

**Architecture:** Two JSON dictionary files are edited: `programs.json` (add a `"vnu_uet"` section) and `methods.json` (rename `"uet"` to `"vnu_uet"` to match `school_id`). No Python changes. The normalizer loads school-specific entries by `school_id`; since sources use `school_id="vnu_uet"`, both files need that key.

**Tech Stack:** JSON, Python (normalization test script).

**Prerequisite:** Plan 03 complete — parser returns raw facts with real program names and method text.

---

### Task 1: Understand What the Parser Currently Produces

**Files:**
- Read only. No changes yet.

- [ ] **Step 1: Collect raw program names and method text from parser output**

Run the diagnostic script from Plan 03 and capture output:

```
python scripts/test_vnu_uet_parser.py 2>&1 | tee /tmp/vnu_uet_raw_facts.txt
```

From `/tmp/vnu_uet_raw_facts.txt`, write down all unique values of:
- `program_name` across all facts from both sources
- `admission_method_raw` across all facts from both sources

These are the raw surface forms you need to map in the dictionaries.

Example (your actual values will differ):
```
RAW PROGRAM NAMES (UET homepage):
  "Khoa học Máy tính"
  "Kỹ thuật Máy tính"
  "Công nghệ Thông tin (CNTT)"
  "Điện tử - Viễn thông"
  "Cơ điện tử"

RAW PROGRAM NAMES (ĐHQGHN PDF):
  "Khoa học máy tính"
  "Kỹ thuật máy tính"
  "Công nghệ thông tin"
  "Điện tử và Viễn thông"
  "Kỹ thuật cơ điện tử"

RAW METHOD TEXT:
  "xét điểm thi TN THPT"
  "đánh giá năng lực"
  "tuyển thẳng"
  (may be None if parser did not extract method)
```

- [ ] **Step 2: Identify which programs already resolve via _shared entries**

Run:

```python
python - <<'EOF'
import sys; sys.path.insert(0, ".")
from ingestion.normalization.program_mapper import map_program

test_names = [
    "Khoa học Máy tính",
    "Kỹ thuật Máy tính",
    "Công nghệ Thông tin",
    "Điện tử - Viễn thông",
    "Cơ điện tử",
    # add all names from your raw output above
]

for name in test_names:
    pid, canonical = map_program(name, school_id="vnu_uet")
    status = "OK" if pid else "MISSING"
    print(f"  [{status}] {name!r} -> pid={pid!r}, canonical={canonical!r}")
EOF
```

Note every name that prints `[MISSING]` — those need a new `vnu_uet` dictionary entry or an alias added to an existing `_shared` entry.

---

### Task 2: Update `programs.json` — Add VNU-UET Section

**Files:**
- Modify: `ingestion/normalization/dictionaries/programs.json`

- [ ] **Step 1: Write a test that asserts all conflict-bearing programs resolve**

Create `scripts/verify_vnu_uet_normalization.py`:

```python
"""
Assert that VNU-UET program names (from both sources) normalize to
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
    ("Khoa học Máy tính",           "Khoa học máy tính"),
    ("Kỹ thuật Máy tính",           "Kỹ thuật máy tính"),
    ("Công nghệ Thông tin (CNTT)",  "Công nghệ thông tin"),
    ("Điện tử - Viễn thông",        "Điện tử và Viễn thông"),
    ("Cơ điện tử",                  "Kỹ thuật cơ điện tử"),
]

# map_method(raw, school_id) returns a canonical code string if matched,
# or the original raw string as fallback. A "known" canonical code is
# one of the keys in methods.json (thpt_score, school_record, competency_test, etc.)
KNOWN_METHOD_CODES = {
    "thpt_score", "school_record", "talent_admission",
    "combined", "competency_test",
}

METHOD_SAMPLES = [
    "đánh giá năng lực",
    "xét điểm thi TN THPT",
    "tuyển thẳng",
]

print("=== Program mapping ===")
all_ok = True
for uet_name, pdf_name in PROGRAM_PAIRS:
    pid_uet, canon_uet = map_program(uet_name, school_id="vnu_uet")
    pid_pdf, canon_pdf = map_program(pdf_name, school_id="vnu_uet")
    match = pid_uet and pid_uet == pid_pdf
    status = "MATCH" if match else "MISMATCH"
    if not match:
        all_ok = False
    print(f"  [{status}]")
    print(f"    UET  page: {uet_name!r} -> pid={pid_uet!r}")
    print(f"    PDF      : {pdf_name!r} -> pid={pid_pdf!r}")

print("\n=== Method mapping ===")
for raw in METHOD_SAMPLES:
    # map_method returns a single str (canonical code or original raw fallback)
    result = map_method(raw, school_id="vnu_uet")
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
python scripts/verify_vnu_uet_normalization.py
```

Expected: Several `[MISMATCH]` or `[MISSING]` lines and `FAIL` at the end.

- [ ] **Step 3: Update `PROGRAM_PAIRS` with your actual names from Task 1**

Open `scripts/verify_vnu_uet_normalization.py`. Replace the `PROGRAM_PAIRS` list with the actual raw program names you collected in Task 1 Step 1. Include every program that appears in both sources (the conflict-bearing set).

- [ ] **Step 4: Add the `"vnu_uet"` section to `programs.json`**

Open `ingestion/normalization/dictionaries/programs.json`. After the closing `}` of the `"hust"` section and before the final `}` of the file, add a `"vnu_uet"` section.

VNU-UET's 2026 programs (add only programs you actually observed in both sources from Task 1; remove any that didn't appear):

```json
  "vnu_uet": {
    "computer_science_uet": {
      "canonical_name": "Khoa học Máy tính",
      "aliases": [
        "Khoa học máy tính",
        "Computer Science",
        "KH Máy tính",
        "CS",
        "Công nghệ Thông tin - Khoa học Máy tính"
      ],
      "field": "technology"
    },
    "computer_engineering_uet": {
      "canonical_name": "Kỹ thuật Máy tính",
      "aliases": [
        "Kỹ thuật máy tính",
        "Computer Engineering",
        "KT Máy tính",
        "CE"
      ],
      "field": "technology"
    },
    "information_technology_uet": {
      "canonical_name": "Công nghệ Thông tin",
      "aliases": [
        "Công nghệ thông tin",
        "Information Technology",
        "CNTT",
        "Công nghệ Thông tin (CNTT)",
        "IT"
      ],
      "field": "technology"
    },
    "electronics_telecom_uet": {
      "canonical_name": "Kỹ thuật Điện tử - Viễn thông",
      "aliases": [
        "Điện tử - Viễn thông",
        "Điện tử và Viễn thông",
        "Electronics and Telecommunications",
        "ĐTVT",
        "Điện tử Viễn thông"
      ],
      "field": "engineering"
    },
    "mechatronics_uet": {
      "canonical_name": "Kỹ thuật Cơ điện tử",
      "aliases": [
        "Cơ điện tử",
        "Kỹ thuật cơ điện tử",
        "Mechatronics",
        "Mechatronics Engineering"
      ],
      "field": "engineering"
    },
    "artificial_intelligence_uet": {
      "canonical_name": "Trí tuệ Nhân tạo",
      "aliases": [
        "Trí tuệ nhân tạo",
        "Artificial Intelligence",
        "AI",
        "Công nghệ Trí tuệ Nhân tạo"
      ],
      "field": "technology"
    },
    "information_security_uet": {
      "canonical_name": "An toàn Thông tin",
      "aliases": [
        "An toàn thông tin",
        "Information Security",
        "Cyber Security",
        "ATTT"
      ],
      "field": "technology"
    }
  }
```

**Important — only add entries for programs that showed [MISSING] in Task 1 Step 2.** Do not add a `vnu_uet` entry for programs already covered by a `_shared` entry. For example, if "Khoa học Máy tính" already maps to `computer_science` (shared), do NOT add `computer_science_uet` — that would create a duplicate key in the merged dict without helping. Only use this section for programs with no match in `_shared`: typically "Kỹ thuật Máy tính", "Trí tuệ Nhân tạo", "An toàn Thông tin", and similar VNU-UET-specific programs.

The aliases for each entry must include the exact string returned by `fact.program_name` for each source.

- [ ] **Step 5: Confirm JSON is valid**

```
python -c "import json; d = json.load(open('ingestion/normalization/dictionaries/programs.json')); print('vnu_uet programs:', list(d.get('vnu_uet', {}).keys()))"
```

Expected: Lists the program IDs you added.

---

### Task 3: Fix `methods.json` — Rename `"uet"` to `"vnu_uet"`

**Files:**
- Modify: `ingestion/normalization/dictionaries/methods.json`

The existing `"uet"` section in `methods.json` was written before the `school_id="vnu_uet"` convention was finalized. The method mapper calls `_load_dict(school_id)` which looks for `methods["vnu_uet"]`. The `"uet"` key is currently unreachable when `school_id="vnu_uet"`.

- [ ] **Step 1: Rename the `"uet"` key to `"vnu_uet"` in methods.json**

Open `ingestion/normalization/dictionaries/methods.json`. Find this block:

```json
  "uet": {
    "competency_test": {
      "canonical_name": "Đánh giá năng lực (ĐGNL ĐHQGHN)",
      "aliases": [
        "đánh giá năng lực",
        "ĐGNL",
        "bài thi ĐGNL",
        "ĐGNL ĐHQGHN",
        "kỳ thi ĐGNL"
      ]
    }
  },
```

Replace `"uet":` with `"vnu_uet":`.

After edit:
```json
  "vnu_uet": {
    "competency_test": {
      "canonical_name": "Đánh giá năng lực (ĐGNL ĐHQGHN)",
      "aliases": [
        "đánh giá năng lực",
        "ĐGNL",
        "bài thi ĐGNL",
        "ĐGNL ĐHQGHN",
        "kỳ thi ĐGNL"
      ]
    }
  },
```

- [ ] **Step 2: Add any missing method entries observed in Task 1**

From your Task 1 Step 1 raw output, check which `admission_method_raw` values appear. Add aliases for any that don't map yet. Common additions for VNU-UET:

```json
  "vnu_uet": {
    "competency_test": {
      "canonical_name": "Đánh giá năng lực (ĐGNL ĐHQGHN)",
      "aliases": [
        "đánh giá năng lực",
        "ĐGNL",
        "bài thi ĐGNL",
        "ĐGNL ĐHQGHN",
        "kỳ thi ĐGNL",
        "bài thi đánh giá năng lực",
        "Đánh giá năng lực ĐHQGHN"
      ]
    },
    "talent_admission": {
      "canonical_name": "Xét tuyển tài năng",
      "aliases": [
        "tuyển thẳng",
        "xét tuyển tài năng",
        "tuyển thẳng theo quy chế bộ GD&ĐT",
        "xét tuyển thẳng",
        "miễn thi"
      ]
    }
  },
```

Only add methods that appear in your actual Task 1 output.

- [ ] **Step 3: Confirm JSON is valid**

```
python -c "import json; d = json.load(open('ingestion/normalization/dictionaries/methods.json')); print('vnu_uet methods:', list(d.get('vnu_uet', {}).keys()))"
```

Expected: `vnu_uet methods: ['competency_test', 'talent_admission']` (or whichever you added).

---

### Task 4: Invalidate Normalization Cache and Verify

The normalizer uses a module-level `_PROGRAMS_CACHE` dict. Because this cache is populated at import time in the same Python process, you must restart the Python process after editing the JSON files.

- [ ] **Step 1: Run the verification script in a fresh process**

```
python scripts/verify_vnu_uet_normalization.py
```

Expected: All `[MATCH]` and `[OK]` lines, then `PASS`.

If a program pair still shows `[MISMATCH]`:
- Both names must resolve to the **same** `program_id`. Check that the alias list for that entry in `programs.json` covers the exact raw string returned by the parser for that source.
- Use `map_program("<raw name>", school_id="vnu_uet")` interactively to debug:
  ```python
  python -c "import sys; sys.path.insert(0,''); from ingestion.normalization.program_mapper import map_program; print(map_program('Khoa học máy tính', school_id='vnu_uet'))"
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
sources = pipeline.registry.get_sources_by_school("vnu_uet")

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
- `admission_method` is non-null for at least some records

If `program_id="NONE"` for any conflict-bearing program, the alias is missing — add it to `programs.json` and re-run.

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
        scripts/verify_vnu_uet_normalization.py
git commit -m "feat: add VNU-UET program and method normalization entries"
```

---

### Self-Check Before Proceeding to Plan 05

- `python scripts/verify_vnu_uet_normalization.py` prints PASS
- All conflict-bearing program pairs map to the **same** `program_id` from both sources
- `admission_method` is non-null for at least the competency test and THPT methods
- All existing tests pass
