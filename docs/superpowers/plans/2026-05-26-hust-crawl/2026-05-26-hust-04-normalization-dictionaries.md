# HUST Normalization Dictionary Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every HUST program-method tuple resolves to a non-null `program_id`, non-null `program_name_canonical`, and non-null `admission_method` that match across both HUST sources. The HUST dictionaries already have substantial coverage from commit `b9953db`; this plan inventories what exists, adds only what's missing, and verifies the cross-source invariant holds.

Note: per the Plan 01 PROCEED_WITH_CAVEATS override, HUST 2026's two sources are not expected to disagree on quota values — but they MUST still resolve to the same canonical (program_id, admission_method) keys so that DB rows from both sources align in `canonical_admission_records`. The invariant verified here is exactly that key-alignment.

**Architecture:** Three JSON dictionary files are touched: `programs.json` (already has `_shared` + a `hust` section with 22 niche programs), `methods.json` (already has `_shared` thpt_score/school_record/talent_admission/combined + `hust` competency_test for TSA), and `combo_method_rules.json` (already has a `hust` section). Edits are additive — no renaming, no overwriting. The normalizer loads school-specific entries by `school_id`; sources use `school_id="hust"`.

**Tech Stack:** JSON, Python (normalization test script).

**Prerequisite:** Plan 03 complete — both HUST sources return facts with `program_name`, `quota_raw`, and `admission_method_raw` populated. Source #1 (listing) should yield ≥10 facts; Source #2 (announcement HTML) should yield ≥60.

---

### Task 1: Inventory the Raw Output the Parsers Produce

**Files:**
- Read only. No changes yet.

- [ ] **Step 1: Collect raw program names and method text from both sources**

Run Plan 03's diagnostic script and capture output:

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe scripts/test_hust_parser.py 2>&1 | Tee-Object -FilePath docs/ingestion/_hust_raw_facts.txt
```

From `docs/ingestion/_hust_raw_facts.txt`, capture all unique values of:
- `program_name` across all facts from both sources
- `admission_method_raw` across all facts from both sources

These are the raw surface forms that must map in the dictionaries.

Write them down in this format:

```
RAW PROGRAM NAMES (HUST program listing — Source #1):
  "Khoa học Máy tính"
  "Kỹ thuật Máy tính"
  "Công nghệ Thông tin"
  "Kỹ thuật Điện tử - Viễn thông"
  "Kỹ thuật Cơ điện tử"
  ...

RAW PROGRAM NAMES (HUST announcement HTML — Source #2):
  "Khoa học máy tính"
  "Kỹ thuật máy tính"
  "Công nghệ thông tin"
  "Kỹ thuật Điện tử – Viễn thông"
  ...

RAW METHOD TEXT (both sources, unique values):
  "xét điểm thi TN THPT"
  "đánh giá tư duy"
  "xét tuyển tài năng"
  "kết hợp"
  ...
```

Save this list to your working notes — Tasks 2 and 3 reference it.

- [ ] **Step 2: Probe the current normalization output for those raw names**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from ingestion.normalization.program_mapper import map_program

# Replace this list with every unique raw program_name from Step 1.
test_names = [
    'Khoa học Máy tính',
    'Kỹ thuật Máy tính',
    'Công nghệ Thông tin',
    'Kỹ thuật Điện tử - Viễn thông',
    'Kỹ thuật Cơ điện tử',
    # add ALL raw names captured above
]

print('Probing current dictionary coverage:')
missing = []
for name in test_names:
    pid, canonical = map_program(name, school_id='hust')
    status = 'OK' if pid else 'MISSING'
    if not pid:
        missing.append(name)
    print(f'  [{status}] {name!r} -> pid={pid!r}, canonical={canonical!r}')
print()
print(f'{len(missing)} missing entries:', missing)
"
```

Save the list of `[MISSING]` names — those are what Task 2 will add. Names that resolve via `_shared` (e.g., `computer_science`) don't need a `hust` entry; only add `hust`-section entries for names with no shared match.

- [ ] **Step 3: Probe the current method dictionary coverage**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from ingestion.normalization.method_mapper import map_method

# Replace with every unique admission_method_raw value from Step 1.
test_methods = [
    'xét điểm thi TN THPT',
    'đánh giá tư duy',
    'xét tuyển tài năng',
    'kết hợp',
    # add all raw method strings observed
]

print('Probing current method dictionary coverage:')
for raw in test_methods:
    result = map_method(raw, school_id='hust')
    print(f'  {raw!r} -> {result!r}')
"
```

The expected canonical codes are: `thpt_score`, `competency_test`, `talent_admission`, `combined`, `school_record`. Any method that does not resolve to one of these falls back to the raw string and is added in Task 3.

---

### Task 2: Update `programs.json` — Add Missing HUST Aliases / Entries

**Files:**
- Modify: `ingestion/normalization/dictionaries/programs.json`
- Create: `scripts/verify_hust_normalization.py`

- [ ] **Step 1: Write the normalization verification script**

Create `scripts/verify_hust_normalization.py`:

```python
"""
Assert that HUST program names (from BOTH sources) normalize to the same
program_id and admission_method. This is the key-alignment invariant that
makes rows from both sources land on the same canonical (program_id,
admission_method) pair in canonical_admission_records — needed even though
HUST 2026 is not expected to produce divergent quota values.
"""
import sys
sys.path.insert(0, ".")
from ingestion.normalization.program_mapper import map_program
from ingestion.normalization.method_mapper import map_method

# Pairs of (listing_name, announcement_name) for the same HUST program code.
# Pull these from the pre-flight Program Name Mapping Table, plus any program
# pairs surfaced by the Plan 04 Task 1 raw-name inventory.
# Format: (listing_name, announcement_name)
PROGRAM_PAIRS = [
    ("Khoa học Máy tính",           "Khoa học máy tính"),
    ("Kỹ thuật Máy tính",           "Kỹ thuật máy tính"),
    ("Công nghệ Thông tin",         "Công nghệ thông tin"),
    ("Kỹ thuật Điện tử - Viễn thông", "Kỹ thuật Điện tử – Viễn thông"),
    ("Kỹ thuật Cơ điện tử",         "Kỹ thuật cơ điện tử"),
]

# Methods that both sources are expected to emit. The canonical codes are
# keys in methods.json. A "known" canonical code is one of these.
KNOWN_METHOD_CODES = {
    "thpt_score", "school_record", "talent_admission",
    "combined", "competency_test",
}

METHOD_SAMPLES = [
    "xét điểm thi TN THPT",
    "đánh giá tư duy",
    "xét tuyển tài năng",
    "kết hợp",
]

all_ok = True

print("=== Program mapping (cross-source invariant) ===")
for listing_name, announcement_name in PROGRAM_PAIRS:
    pid_listing, canon_listing = map_program(listing_name, school_id="hust")
    pid_announcement, canon_announcement = map_program(announcement_name, school_id="hust")
    match = pid_listing and pid_listing == pid_announcement
    status = "MATCH" if match else "MISMATCH"
    if not match:
        all_ok = False
    print(f"  [{status}]")
    print(f"    listing      : {listing_name!r} -> pid={pid_listing!r}  canon={canon_listing!r}")
    print(f"    announcement : {announcement_name!r} -> pid={pid_announcement!r}  canon={canon_announcement!r}")

print("\n=== Method mapping ===")
for raw in METHOD_SAMPLES:
    result = map_method(raw, school_id="hust")
    mapped = result in KNOWN_METHOD_CODES
    status = "OK" if mapped else "UNMAPPED"
    if not mapped:
        all_ok = False
    print(f"  [{status}] {raw!r} -> {result!r}")

if all_ok:
    print("\nPASS")
else:
    print("\nFAIL — fix the dictionaries above and re-run")
    sys.exit(1)
```

Replace the `PROGRAM_PAIRS` list and `METHOD_SAMPLES` list with **all** program pairs (every program code appearing in both Source #1 and Source #2) and raw method values from your Plan 01 mapping table and Task 1 inventory.

- [ ] **Step 2: Run it to confirm it fails before dictionary edits**

```powershell
.venv/Scripts/python.exe scripts/verify_hust_normalization.py
```

Expected: several `[MISMATCH]` or `[UNMAPPED]` lines and `FAIL` at the end. If it prints `PASS` already, the dictionaries are complete and you can skip to Task 4.

- [ ] **Step 3: Add missing alias entries to `programs.json`**

For each `[MISMATCH]` or `[MISSING]` name from Task 1 Step 2, decide:

**Case A — name should map to a `_shared` entry but doesn't yet.** Open `ingestion/normalization/dictionaries/programs.json`, find the matching `_shared` entry (e.g., `_shared.computer_science`), and add the raw name to its `aliases` array. Example:

```json
  "_shared": {
    "computer_science": {
      "canonical_name": "Khoa học Máy tính",
      "aliases": [
        "Khoa học máy tính",
        "khoa hoc may tinh",
        ...,
        "Khoa học Máy tính",          // ← add raw name from listing source if not present
        "Khoa học máy tính (CT TT)",  // ← any HUST-specific variant observed
        ...
      ]
    }
  }
```

**Case B — program is HUST-specific (no `_shared` match makes sense).** Add it to the `"hust"` section. The existing `hust` section already has 22 entries; append your new entry next to them. Example:

```json
  "hust": {
    "math_informatics": {
      "canonical_name": "Toán - Tin",
      "aliases": ["Toán - Tin", "Toán Tin"]
    },
    // ... existing entries ...
    "data_analytics_economics": {        // ← new entry
      "canonical_name": "Phân tích Kinh doanh",
      "aliases": [
        "Phân tích Kinh doanh",
        "Phân tích kinh doanh",
        "Business Analytics"
      ]
    }
  }
```

**Important:**
- The aliases must include the **exact raw string** each parser emits for that program.
- Subtle differences matter: `"Kỹ thuật Điện tử - Viễn thông"` (ASCII hyphen-minus) vs `"Kỹ thuật Điện tử – Viễn thông"` (Unicode en-dash) are different strings; add both aliases.
- Case matters per the program mapper's normalization logic — re-check if the mapper does case-insensitive matching or not by reading `ingestion/normalization/program_mapper.py`.

- [ ] **Step 4: Confirm JSON parses cleanly**

```powershell
.venv/Scripts/python.exe -c "
import json
d = json.load(open('ingestion/normalization/dictionaries/programs.json', encoding='utf-8'))
print('top-level keys:', list(d.keys()))
print('hust entries:', len(d.get('hust', {})))
print('_shared entries:', len(d.get('_shared', {})))
"
```

Expected: valid JSON; the `hust` count is ≥ its prior value, `_shared` count unchanged unless you added new shared programs.

---

### Task 3: Update `methods.json` — Cover All Method Strings Observed

**Files:**
- Modify: `ingestion/normalization/dictionaries/methods.json`

The existing `hust` section in `methods.json` has only `competency_test` (mapping TSA / Đánh giá tư duy). `_shared` already covers `thpt_score`, `school_record`, `talent_admission`, `combined`.

- [ ] **Step 1: For each raw method from Task 1 Step 3 that mapped to itself (UNMAPPED), add an alias**

Open `ingestion/normalization/dictionaries/methods.json`.

**Case A — raw method should resolve to an existing `_shared` code.** Append the raw text to that code's `aliases`. Example: if `"xét điểm thi TN THPT"` is UNMAPPED, find `_shared.thpt_score.aliases` and add it:

```json
  "_shared": {
    "thpt_score": {
      "canonical_name": "Xét tuyển dựa trên điểm thi tốt nghiệp THPT",
      "aliases": [
        "thpt_score",
        "xét tuyển bằng điểm thi THPT",
        "điểm thi tốt nghiệp THPT",
        ...
        "xét điểm thi TN THPT",        // ← add
        "xét tuyển dựa trên kết quả thi TN THPT"  // ← add other variants
      ]
    }
  }
```

**Case B — raw method is HUST-specific (e.g., a TSA-specific phrase).** Add to the existing `hust.competency_test.aliases` array. Existing canonical name is "Đánh giá tư duy (TSA)".

- [ ] **Step 2: If a new method canonical-code is observed (not present in any school's dictionary)**

Rare — add a new key under `_shared` (preferred) or under `hust` (school-specific only). Example, if HUST publishes a brand-new method category in 2026:

```json
  "_shared": {
    ...,
    "international_certificate": {
      "canonical_name": "Xét tuyển bằng chứng chỉ quốc tế",
      "aliases": [
        "international_certificate",
        "chứng chỉ quốc tế",
        "IELTS",
        "SAT",
        "ACT",
        "A-level"
      ]
    }
  }
```

Only add if the raw method text from Task 1 doesn't fit any existing canonical code. Otherwise prefer aliasing an existing code.

- [ ] **Step 3: Confirm JSON parses cleanly**

```powershell
.venv/Scripts/python.exe -c "
import json
d = json.load(open('ingestion/normalization/dictionaries/methods.json', encoding='utf-8'))
print('top-level keys:', list(d.keys()))
print('hust methods:', list(d.get('hust', {}).keys()))
print('_shared methods:', list(d.get('_shared', {}).keys()))
"
```

---

### Task 4: Update `combo_method_rules.json` If Needed

**Files:**
- Modify (only if needed): `ingestion/normalization/dictionaries/combo_method_rules.json`

This file maps `subject_combinations_raw` patterns to method inferences. The existing `hust` section already covers the standard combinations. Update **only if** Task 1 surfaced a subject combination (or program that uses one) that isn't already handled.

- [ ] **Step 1: Check whether updates are needed**

Compare the `subject_combinations_raw` values seen in Plan 03's diagnostic to the existing `hust` section in `combo_method_rules.json`. Most cases will already be covered by the inherited `_shared` rules.

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
import json
d = json.load(open('ingestion/normalization/dictionaries/combo_method_rules.json', encoding='utf-8'))
print('hust combo rules:')
for k, v in (d.get('hust') or {}).items():
    print(f'  {k}: {v}')
"
```

- [ ] **Step 2: If updates needed, append to the `hust` section**

Mirror the shape of existing entries. Do not modify `_shared` unless the rule is universal across schools.

- [ ] **Step 3: Confirm JSON parses cleanly** (same as Tasks 2/3 Step "confirm JSON" steps).

---

### Task 5: Invalidate Normalization Cache and Verify

The normalizer caches dictionary contents at module import. Edits to JSON files are picked up only on a fresh Python process (or by clearing the module-level cache, as `db/reimport.py` does).

- [ ] **Step 1: Run the verification script in a fresh process**

```powershell
.venv/Scripts/python.exe scripts/verify_hust_normalization.py
```

Expected: all `[MATCH]` and `[OK]` lines, then `PASS`.

If a program pair still shows `[MISMATCH]`:
- Both raw names must resolve to the **same** `program_id`. Check that the alias list for that entry covers the exact raw string returned by each parser for each source.
- Debug interactively:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "from ingestion.normalization.program_mapper import map_program; print(map_program('<RAW NAME>', school_id='hust'))"
  ```

If a method shows `[UNMAPPED]`:
- The raw method text isn't in any school's aliases for the expected canonical code. Add it per Task 3.

- [ ] **Step 2: Run the full normalization path on actual facts**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.fetchers.fetch_dispatcher import dispatch_fetch
from ingestion.router.document_router import route_document
from ingestion.parsers.parser_dispatcher import dispatch_parser
from ingestion.extractors.admission_extractor import extract_admission_facts
from ingestion.normalization.normalizer import normalize_facts
from ingestion.models.pipeline_models import SourceReference

pipeline = IngestionPipeline()
sources = pipeline.registry.get_sources_by_school('hust')

for source in sources:
    print(f'\nSource: {source.source_id}')
    fetch = dispatch_fetch(source.root_url, source)
    doc_type = route_document(fetch)
    parsed = dispatch_parser(fetch, doc_type, source)
    if isinstance(parsed, list):
        facts = parsed
    else:
        source_ref = SourceReference(
            source_id=source.source_id,
            source_url=source.root_url,
            school_id=source.school_id,
            trust_level=source.trust_level,
        )
        facts = extract_admission_facts(parsed, source_ref, source.school_name)
    records = normalize_facts(facts, school_id='hust')
    print(f'  {len(facts)} facts -> {len(records)} normalized records')
    for r in records[:5]:
        pid = r.program_id or 'NONE'
        pname = r.program_name_canonical or 'NONE'
        method = r.admission_method or 'NONE'
        quota_obj = r.quota
        quota_val = quota_obj.value if quota_obj else 'NONE'
        print(f'  program_id={pid!r}  canon={pname!r}  method={method!r}  quota={quota_val}')
"
```

Acceptance criteria:
- `program_id` is non-null for ≥10 facts per source
- `program_name_canonical` is the same string for the same logical program across both sources
- `admission_method` is non-null for ≥10 records per source, and resolves to the same canonical code across both sources for at least one shared method (e.g., both yield `"thpt_score"` for the THPT pathway)

If any program shows `program_id="NONE"`, the alias is missing — add it to `programs.json` and re-run.

---

### Task 6: Commit Dictionary Updates

- [ ] **Step 1: Run all existing tests**

```powershell
.venv/Scripts/python.exe -m pytest tests/ingestion/ -v
```

Expected: all green. Dictionary additions shouldn't break any tests since aliases are additive.

- [ ] **Step 2: Commit**

```powershell
git add ingestion/normalization/dictionaries/programs.json `
        ingestion/normalization/dictionaries/methods.json `
        ingestion/normalization/dictionaries/combo_method_rules.json `
        scripts/verify_hust_normalization.py
git commit -m "feat(ingestion): extend HUST normalization aliases for 2026 cross-source coverage"
```

---

### Self-Check Before Proceeding to Plan 05

- `.venv/Scripts/python.exe scripts/verify_hust_normalization.py` prints PASS
- All program pairs from the Plan 01 mapping table (and any additional pairs surfaced by Task 1) resolve to the **same** `program_id` from both sources
- `admission_method` is non-null for ≥10 records per source and at least one canonical code (e.g., `thpt_score`) is shared across both sources for the same program
- All existing tests pass
