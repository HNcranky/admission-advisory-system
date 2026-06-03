# NEU Source Registry Entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add NEU's 2026 admission sources to the source registry so the ingestion pipeline discovers and processes them.

**Architecture:** Append two NEU `SourceEntry`-compatible dicts to `ingestion/registry/seeds/initial_sources.json`. `IngestionPipeline.__init__` already loads this file automatically (see `ingestion/pipeline/ingestion_pipeline.py:46–50`). No Python changes required unless the seed file does not yet exist.

**Tech Stack:** JSON, Python (verification script), psql not needed for this plan.

**Prerequisite:** `docs/ingestion/neu-preflight-findings.md` exists with Outcome = PASS and contains the confirmed source URLs.

---

### Task 1: Inspect Existing Registry State

**Files:**
- Read: `ingestion/registry/seeds/initial_sources.json` (check if it exists and note current entries)
- Read: `ingestion/registry/models.py` (confirm SourceEntry field names and enum values)

- [ ] **Step 1: Check whether the seed file already exists**

Run:
```
ls ingestion/registry/seeds/
```

If `initial_sources.json` exists, read it and note existing entries (e.g., HUST, VNU-UET entries). If the directory doesn't exist:
```
mkdir -p ingestion/registry/seeds
```

- [ ] **Step 2: Confirm SourceType and FetchStrategy string values**

Open `ingestion/registry/models.py`. Confirm the string values that Pydantic serializes for the enums (the model uses `use_enum_values = True`):
- `SourceType.ADMISSION_HOMEPAGE` → `"admission_homepage"`
- `SourceType.ADMISSION_PROPOSAL` → check what string value this produces (may be `"admission_proposal"` or `"proposal_pdf"` depending on the enum definition)
- `FetchStrategy.HTTP` → `"http"`

Note the exact string values so the JSON entries match.

- [ ] **Step 3: Read existing HUST and VNU-UET trust_level values**

From `initial_sources.json` (or from the findings documents in `docs/ingestion/`), note:
- The `trust_level` used for `proposal_pdf` / `admission_proposal` sources (expected: 5)
- The `trust_level` used for `admission_homepage` sources (expected: 4)
- The `trust_level` used for `program_page` sources (expected: 3)

NEU must use the same numeric values for parity.

---

### Task 2: Write a Verification Script (Test First)

**Files:**
- Create: `scripts/verify_neu_registry.py`

- [ ] **Step 1: Write the verification script**

Create `scripts/verify_neu_registry.py`:

```python
"""Verify NEU sources appear in the registry."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.pipeline.ingestion_pipeline import IngestionPipeline

pipeline = IngestionPipeline()
sources = pipeline.registry.get_sources_by_school("neu")

print(f"NEU sources: {len(sources)}")
for s in sources:
    print(f"  {s.source_id:45s}  type={s.source_type:22s}  trust={s.trust_level}  active={s.active}")

assert len(sources) >= 2, f"Expected ≥2 NEU sources, got {len(sources)}"
source_types = {s.source_type for s in sources}
assert "admission_homepage" in source_types, "Missing admission_homepage source"
# The second source is either admission_proposal or proposal_pdf depending on SourceType enum values.
# Adjust the string below to match the actual enum value from Task 1 Step 2.
assert (
    "admission_proposal" in source_types or "proposal_pdf" in source_types
), "Missing proposal source"
print("PASS")
```

- [ ] **Step 2: Run to confirm it fails before adding entries**

```
python scripts/verify_neu_registry.py
```

Expected: `AssertionError: Expected ≥2 NEU sources, got 0`

---

### Task 3: Create / Update the Source Registry Seed File

**Files:**
- Modify (or create): `ingestion/registry/seeds/initial_sources.json`

- [ ] **Step 1: Get the confirmed source URLs from pre-flight findings**

Open `docs/ingestion/neu-preflight-findings.md`. Find the "Sources Confirmed" table. Copy:
- The exact NEU homepage URL (typically `https://tuyensinh.neu.edu.vn/`)
- The exact NEU proposal PDF URL (or replacement HTML URL if PDF was excluded during pre-flight)

- [ ] **Step 2: Add NEU entries to initial_sources.json**

If the file does not exist, create it as a JSON array. If it already contains HUST or VNU-UET entries, append the two NEU objects to the existing array. The file must remain a valid JSON array.

Add these two objects (replace `root_url` values with the confirmed URLs from the findings document):

```json
  {
    "source_id": "neu_admission_homepage_2026",
    "school_id": "neu",
    "school_name": "Trường Đại học Kinh tế Quốc dân",
    "source_type": "admission_homepage",
    "root_url": "https://tuyensinh.neu.edu.vn/",
    "trust_level": 4,
    "priority": 2,
    "fetch_strategy": "http",
    "parser_profile": "default_html",
    "update_frequency_hint": "yearly",
    "is_official": true,
    "active": true
  },
  {
    "source_id": "neu_proposal_2026",
    "school_id": "neu",
    "school_name": "Trường Đại học Kinh tế Quốc dân",
    "source_type": "admission_proposal",
    "root_url": "<PASTE PDF URL FROM PRE-FLIGHT FINDINGS HERE>",
    "trust_level": 5,
    "priority": 1,
    "fetch_strategy": "http",
    "parser_profile": "default_pdf",
    "update_frequency_hint": "yearly",
    "is_official": true,
    "active": true
  }
```

**Notes on field values:**

- `source_type`: Use the exact string from Task 1 Step 2 (the enum's serialized value). For the PDF, this is typically `"admission_proposal"` — verify against the enum definition.
- `trust_level`: `5` for the proposal/PDF (highest authority), `4` for the homepage. Match whatever values HUST and VNU-UET use.
- `priority`: `1` for the proposal (crawled first), `2` for the homepage.
- `parser_profile`: Start with `"default_pdf"` for the PDF and `"default_html"` for the homepage. Plan 03 may update the homepage profile to `"neu_admission_page"` if a thin parser is needed.
- If the second source is an HTML replacement (PDF was excluded): use `"source_type": "admission_homepage"` with an appropriate `source_id` like `"neu_announcement_html_2026"` and `"trust_level": 4`.

- [ ] **Step 3: Validate the JSON is parseable**

```
python -c "import json; data = json.load(open('ingestion/registry/seeds/initial_sources.json')); print(f'Valid JSON: {len(data)} entries')"
```

Expected: `Valid JSON: N entries` where N is the existing count plus 2.

---

### Task 4: Verify Registry Loads NEU Sources

- [ ] **Step 1: Run the verification script**

```
python scripts/verify_neu_registry.py
```

Expected output:
```
NEU sources: 2
  neu_admission_homepage_2026             type=admission_homepage        trust=4  active=True
  neu_proposal_2026                       type=admission_proposal        trust=5  active=True
PASS
```

- [ ] **Step 2: Verify via the CLI**

```
python -m ingestion.main --list-schools
```

Expected: A row for `neu` appears with `active_sources=2`.

---

### Task 5: Run Existing Pipeline Tests as Regression Gate

**Files:**
- No changes. This confirms the new seed file didn't break anything.

- [ ] **Step 1: Run the ingestion test suite**

```
python -m pytest tests/ingestion/ -v
```

Expected: All existing tests pass. If new failures appear, the JSON is likely malformed or imports are broken — fix before committing.

---

### Task 6: Commit Registry Entries

- [ ] **Step 1: Commit**

```bash
git add ingestion/registry/seeds/initial_sources.json scripts/verify_neu_registry.py
git commit -m "feat: add NEU 2026 sources to source registry seed"
```

---

### Self-Check Before Proceeding to Plan 03

- `python scripts/verify_neu_registry.py` prints PASS
- `python -m ingestion.main --list-schools` shows `neu` with 2 active sources
- Both source URLs are real, confirmed-reachable URLs (not placeholder text) — copied from `docs/ingestion/neu-preflight-findings.md`
- All existing tests pass
