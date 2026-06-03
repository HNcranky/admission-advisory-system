# VNU-UET Source Registry Entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add VNU-UET's 2026 admission sources to the source registry so the ingestion pipeline discovers and processes them.

**Architecture:** Create `ingestion/registry/seeds/initial_sources.json` as a JSON array of `SourceEntry`-compatible dicts. `IngestionPipeline.__init__` already loads this file automatically (see `ingestion/pipeline/ingestion_pipeline.py:46–50`). No Python changes required.

**Tech Stack:** JSON, Python (verification script), psql not needed for this plan.

**Prerequisite:** `docs/ingestion/vnu-uet-preflight-findings.md` exists with Outcome = PASS and contains the confirmed source URLs.

---

### Task 1: Inspect Existing Registry State

**Files:**
- Read: `ingestion/registry/seeds/` (check if `initial_sources.json` exists)
- Read: `ingestion/registry/models.py` (confirm SourceEntry field names and enum values)

- [ ] **Step 1: Check whether the seed file already exists**

Run:
```
ls ingestion/registry/seeds/
```

If `initial_sources.json` exists, read it and note existing entries. If the directory doesn't exist, create it:
```
mkdir -p ingestion/registry/seeds
```

- [ ] **Step 2: Confirm SourceType and FetchStrategy string values**

Open `ingestion/registry/models.py`. Confirm:
- `SourceType.ADMISSION_HOMEPAGE` serializes as `"admission_homepage"`
- `SourceType.PROPOSAL_PDF` serializes as `"proposal_pdf"`
- `FetchStrategy.HTTP` serializes as `"http"`

These are the string values that go into the JSON (the model has `use_enum_values = True`).

---

### Task 2: Write a Verification Script (Test First)

**Files:**
- Create: `scripts/verify_vnu_uet_registry.py`

- [ ] **Step 1: Write the verification script**

Create `scripts/verify_vnu_uet_registry.py`:

```python
"""Verify VNU-UET sources appear in the registry."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.pipeline.ingestion_pipeline import IngestionPipeline

pipeline = IngestionPipeline()
sources = pipeline.registry.get_sources_by_school("vnu_uet")

print(f"VNU-UET sources: {len(sources)}")
for s in sources:
    print(f"  {s.source_id:40s}  type={s.source_type:20s}  trust={s.trust_level}  active={s.active}")

assert len(sources) >= 2, f"Expected ≥2 VNU-UET sources, got {len(sources)}"
source_types = {s.source_type for s in sources}
assert "admission_homepage" in source_types, "Missing admission_homepage source"
assert "proposal_pdf" in source_types, "Missing proposal_pdf source"
print("PASS")
```

- [ ] **Step 2: Run to confirm it fails before adding entries**

```
python scripts/verify_vnu_uet_registry.py
```

Expected: `AssertionError: Expected ≥2 VNU-UET sources, got 0`

---

### Task 3: Create the Source Registry Seed File

**Files:**
- Create (or append to): `ingestion/registry/seeds/initial_sources.json`

- [ ] **Step 1: Get the confirmed source URLs from pre-flight findings**

Open `docs/ingestion/vnu-uet-preflight-findings.md`. Find the "Sources Confirmed" table. Copy:
- The exact UET homepage URL (typically `https://uet.vnu.edu.vn/tuyen-sinh-dai-hoc/`)
- The exact ĐHQGHN proposal PDF URL (changes annually — use the one documented in findings)

- [ ] **Step 2: Create initial_sources.json**

If the file does not exist, create `ingestion/registry/seeds/initial_sources.json`:

```json
[
  {
    "source_id": "vnu_uet_admission_homepage_2026",
    "school_id": "vnu_uet",
    "school_name": "Trường Đại học Công nghệ - ĐHQGHN",
    "source_type": "admission_homepage",
    "root_url": "https://uet.vnu.edu.vn/tuyen-sinh-dai-hoc/",
    "trust_level": 4,
    "priority": 2,
    "fetch_strategy": "http",
    "parser_profile": "default_html",
    "update_frequency_hint": "yearly",
    "is_official": true,
    "active": true
  },
  {
    "source_id": "vnuhn_proposal_pdf_2026",
    "school_id": "vnu_uet",
    "school_name": "Trường Đại học Công nghệ - ĐHQGHN",
    "source_type": "proposal_pdf",
    "root_url": "<PASTE PDF URL FROM PRE-FLIGHT FINDINGS HERE>",
    "trust_level": 5,
    "priority": 1,
    "fetch_strategy": "http",
    "parser_profile": "default_pdf",
    "update_frequency_hint": "yearly",
    "is_official": true,
    "active": true
  }
]
```

Replace the `root_url` for `vnuhn_proposal_pdf_2026` with the exact URL from your pre-flight findings document.

If the file already exists with other school entries, append the two VNU-UET objects to the existing array. The file must remain a valid JSON array.

**Trust level rationale:**
- `proposal_pdf` = 5: highest — the ĐHQGHN proposal is the authoritative official record
- `admission_homepage` = 4: official UET source, slightly lower because it may lag the proposal

**Priority rationale (lower = crawled first):**
- `priority: 1` for PDF: crawl first so we get the authoritative quota values early
- `priority: 2` for homepage: second pass for HTML comparison

- [ ] **Step 3: Validate the JSON is parseable**

```
python -c "import json; data = json.load(open('ingestion/registry/seeds/initial_sources.json')); print(f'Valid JSON: {len(data)} entries')"
```

Expected: `Valid JSON: 2 entries` (or more if other entries existed).

---

### Task 4: Verify Registry Loads VNU-UET Sources

- [ ] **Step 1: Run the verification script**

```
python scripts/verify_vnu_uet_registry.py
```

Expected output:
```
VNU-UET sources: 2
  vnu_uet_admission_homepage_2026          type=admission_homepage       trust=4  active=True
  vnuhn_proposal_pdf_2026                  type=proposal_pdf             trust=5  active=True
PASS
```

- [ ] **Step 2: Verify via the CLI**

```
python -m ingestion.main --list-schools
```

Expected: A row for `vnu_uet` appears with `active_sources=2`.

---

### Task 5: Run Existing Pipeline Tests as Regression Gate

**Files:**
- No changes. This confirms the new seed file didn't break anything.

- [ ] **Step 1: Run the ingestion test suite**

```
python -m pytest tests/ingestion/ -v
```

Expected: All existing tests pass. (There are currently two test files: `test_inference_boundaries.py` and `test_llm_extraction_service.py`.) If new failures appear, the JSON is likely malformed or imports are broken — fix before committing.

---

### Task 6: Commit Registry Entries

- [ ] **Step 1: Commit**

```bash
git add ingestion/registry/seeds/initial_sources.json scripts/verify_vnu_uet_registry.py
git commit -m "feat: add VNU-UET 2026 sources to source registry seed"
```

---

### Self-Check Before Proceeding to Plan 03

- `python scripts/verify_vnu_uet_registry.py` prints PASS
- `python -m ingestion.main --list-schools` shows `vnu_uet` with 2 active sources
- Both source URLs are real, confirmed-reachable URLs (not placeholder text)
- All existing tests pass
