# HUST Source Registry Entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Append HUST's 2026 admission sources to the source registry so the ingestion pipeline discovers and processes them, without dropping the existing VNU-UET entries.

**Architecture:** `ingestion/registry/seeds/initial_sources.json` is the seed file `IngestionPipeline.__init__` loads automatically (see `ingestion/pipeline/ingestion_pipeline.py:46–50`). It currently contains 2 VNU-UET entries. This plan **appends** 2 HUST entries (program listing + the 2026 announcement HTML article) to the existing JSON array. After editing the seed file, `python -m db.setup_db` re-seeds the `source_registry` table idempotently. No Python changes required.

**Tech Stack:** JSON, Python (verification script), `python -m db.setup_db` for re-seeding.

**Prerequisite:** Plan 01 complete — `docs/ingestion/hust-preflight-findings.md` exists with the final verdict line `PROCEED_WITH_CAVEATS` (overridden from initial ABORT on 2026-05-26 per Option 2 — HTML announcement as Source #2, accept zero HUST conflicts). Source URLs:
- Source #1 (program listing): `https://ts.hust.edu.vn/training-cate/nganh-dao-tao-dai-hoc`
- Source #2 (2026 announcement HTML): `https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026`

---

### Task 1: Inspect Existing Registry State

**Files:**
- Read: `ingestion/registry/seeds/initial_sources.json`
- Read: `ingestion/registry/models.py` (confirm SourceEntry field names)

- [ ] **Step 1: Confirm the seed file's current contents**

Run:
```powershell
.venv/Scripts/python.exe -c "
import json
d = json.load(open('ingestion/registry/seeds/initial_sources.json', encoding='utf-8'))
print(f'entries: {len(d)}')
for e in d:
    print(f'  {e[\"source_id\"]:40s}  school={e[\"school_id\"]:10s}  type={e[\"source_type\"]}')
"
```

Expected: 2 entries, both for `school_id=vnu_uet`. If the file already contains HUST entries, halt and reconcile — do not duplicate.

- [ ] **Step 2: Confirm SourceEntry field names**

Open `ingestion/registry/models.py`. Confirm the fields used by the existing VNU-UET entries match the model: `source_id`, `school_id`, `school_name`, `source_type`, `root_url`, `trust_level`, `priority`, `fetch_strategy`, `parser_profile`, `update_frequency_hint`, `is_official`, `active`. The values must serialize as strings (the model has `use_enum_values = True`).

- [ ] **Step 3: Confirm DB is up and current source_registry state**

```powershell
docker compose exec -T db psql -U postgres -d admission -c "SELECT source_id, school_id, active FROM source_registry ORDER BY source_id;"
```

Expected: 2 rows for `vnu_uet`. If the DB has rows for HUST already from a prior attempt, decide whether to clear them (`DELETE FROM source_registry WHERE school_id='hust';`) or treat them as authoritative.

---

### Task 2: Write a Verification Script (Test First)

**Files:**
- Create: `scripts/verify_hust_registry.py`

- [ ] **Step 1: Write the verification script**

Create `scripts/verify_hust_registry.py`:

```python
"""Verify HUST sources appear in the registry alongside VNU-UET."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.pipeline.ingestion_pipeline import IngestionPipeline

pipeline = IngestionPipeline()

hust_sources = pipeline.registry.get_sources_by_school("hust")
vnu_uet_sources = pipeline.registry.get_sources_by_school("vnu_uet")

print(f"HUST sources: {len(hust_sources)}")
for s in hust_sources:
    print(f"  {s.source_id:40s}  type={s.source_type:20s}  trust={s.trust_level}  active={s.active}")

print(f"\nVNU-UET sources (must remain intact): {len(vnu_uet_sources)}")
for s in vnu_uet_sources:
    print(f"  {s.source_id:40s}  type={s.source_type:20s}  trust={s.trust_level}  active={s.active}")

assert len(hust_sources) >= 2, f"Expected >=2 HUST sources, got {len(hust_sources)}"
source_types = {s.source_type for s in hust_sources}
assert "program_listing" in source_types, "Missing program_listing source for HUST"

second_source_types = source_types - {"program_listing"}
assert second_source_types, "Missing the chosen Source #2 (news_listing — 2026 announcement HTML)"

assert len(vnu_uet_sources) >= 2, "VNU-UET entries were lost — DO NOT overwrite the seed file"
print("\nPASS")
```

- [ ] **Step 2: Run the script to confirm it fails before adding HUST entries**

```powershell
.venv/Scripts/python.exe scripts/verify_hust_registry.py
```

Expected: `AssertionError: Expected >=2 HUST sources, got 0`. This confirms the verification is wired up correctly.

---

### Task 3: Append HUST Entries to the Seed File

**Files:**
- Modify: `ingestion/registry/seeds/initial_sources.json` (append entries — do NOT overwrite)

The historical lesson called out in spec `2026-05-26-hust-ingestion-design.md` is that whole-file rewrites previously dropped HUST entries when VNU-UET was added (commits `791310b` then `72fe1e6`). This step explicitly appends.

- [ ] **Step 1: Read the confirmed URLs from pre-flight findings**

Open `docs/ingestion/hust-preflight-findings.md`. Find the "Sources Considered" table. Both URLs were already chosen and recorded on 2026-05-26 (Option 2 override):
- Source #1 URL: `https://ts.hust.edu.vn/training-cate/nganh-dao-tao-dai-hoc` (program listing).
- Source #2 URL: `https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026` (2026 admission announcement HTML article — chosen after the proposal PDF and brochure candidates failed; see "Bail-Outs Applied" in the findings doc).

- [ ] **Step 2: Read the current seed file and append HUST entries**

Read the file:
```powershell
.venv/Scripts/python.exe -c "
import json
with open('ingestion/registry/seeds/initial_sources.json', encoding='utf-8') as f:
    print(f.read())
"
```

Then append two new objects to the existing JSON array, **keeping the existing VNU-UET objects intact**. Use `python` to do the edit safely (avoids accidentally rewriting the file):

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
import json
PATH = 'ingestion/registry/seeds/initial_sources.json'
with open(PATH, encoding='utf-8') as f:
    data = json.load(f)

existing_ids = {e['source_id'] for e in data}

new_entries = [
    {
        'source_id': 'hust_program_listing_2026',
        'school_id': 'hust',
        'school_name': 'Đại học Bách khoa Hà Nội',
        'source_type': 'program_listing',
        'root_url': 'https://ts.hust.edu.vn/training-cate/nganh-dao-tao-dai-hoc',
        'trust_level': 5,
        'priority': 2,
        'fetch_strategy': 'http',
        'parser_profile': 'hust_programs',
        'update_frequency_hint': 'yearly',
        'is_official': True,
        'active': True,
    },
    {
        'source_id': 'hust_announcement_html_2026',
        'school_id': 'hust',
        'school_name': 'Đại học Bách khoa Hà Nội',
        'source_type': 'news_listing',
        'root_url': 'https://ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026',
        'trust_level': 5,
        'priority': 1,
        'fetch_strategy': 'http',
        'parser_profile': 'hust_announcement_html',   # Specialized parser added in Plan 03
        'update_frequency_hint': 'yearly',
        'is_official': True,
        'active': True,
    },
]

for e in new_entries:
    if e['source_id'] in existing_ids:
        print(f'SKIP (already present): {e[\"source_id\"]}')
        continue
    data.append(e)
    print(f'APPEND: {e[\"source_id\"]}')

with open(PATH, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f'Total entries now: {len(data)}')
"
```

**Trust level rationale:**
- HUST program listing = 5: it is the school's official admission portal (`ts.hust.edu.vn`).
- HUST 2026 announcement HTML = 5: same official admission portal (`ts.hust.edu.vn`). The article body contains a 78-row `<table>` listing all 68 programs with their codes, planned quotas, and method flags (XTTN / ĐGTD / THPT). Pre-flight verified reachability and full-coverage structure; see findings "HUST 2026 announcement (potential Source #2)" section.

**Priority rationale** (lower = crawled first):
- `priority: 1` for the announcement HTML: crawl first — it has quotas for all 68 programs, vs. the listing's 6/68 published values.
- `priority: 2` for the program listing: second pass.

**Source type rationale:**
- `source_type` values must come from the `SourceType` enum in `ingestion/registry/models.py` (`admission_homepage | news_listing | proposal_pdf | docx_notice | facebook_page | program_page | program_listing`). The announcement article is HTML news content at the `tin-tuc/` path — closest fit is `news_listing`. The semantically-richer label "admission_proposal" does not exist in the enum.

- [ ] **Step 3: Validate JSON is parseable and VNU-UET entries survived**

```powershell
.venv/Scripts/python.exe -c "
import json
d = json.load(open('ingestion/registry/seeds/initial_sources.json', encoding='utf-8'))
print(f'Valid JSON: {len(d)} entries')
schools = {}
for e in d:
    schools.setdefault(e['school_id'], []).append(e['source_id'])
for school, ids in sorted(schools.items()):
    print(f'  {school}: {len(ids)} sources -> {ids}')
"
```

Expected: at least 4 entries total — 2 vnu_uet + 2 hust. If `vnu_uet` count is less than 2, you accidentally overwrote — restore from git (`git checkout HEAD -- ingestion/registry/seeds/initial_sources.json`) and retry the append carefully.

---

### Task 4: Re-Seed the Database and Verify Registry

**Files:**
- No file changes. Side effect: writes to `source_registry` table.

- [ ] **Step 1: Re-run the seed loader**

```powershell
.venv/Scripts/python.exe -m db.setup_db
```

Expected: the migrations are reported as already applied (or idempotently re-applied), and the seed step reports inserting 2 new HUST entries (the existing VNU-UET ones are skipped via the seed loader's `ON CONFLICT (source_id) DO NOTHING`).

- [ ] **Step 2: Verify DB contents**

```powershell
docker compose exec -T db psql -U postgres -d admission -c "SELECT source_id, school_id, source_type, trust_level, active FROM source_registry ORDER BY school_id, source_id;"
```

Expected: at least 4 rows — 2 vnu_uet + 2 hust.

- [ ] **Step 3: Run the verification script**

```powershell
.venv/Scripts/python.exe scripts/verify_hust_registry.py
```

Expected output:
```
HUST sources: 2
  hust_announcement_html_2026              type=news_listing               trust=5  active=True
  hust_program_listing_2026                type=program_listing            trust=5  active=True

VNU-UET sources (must remain intact): 2
  vnu_uet_admission_homepage_2026          type=admission_homepage         trust=4  active=True
  vnuhn_proposal_pdf_2026                  type=proposal_pdf               trust=5  active=True

PASS
```

- [ ] **Step 4: Verify via the CLI**

```powershell
.venv/Scripts/python.exe -m ingestion.main --list-schools
```

Expected: rows for both `hust` and `vnu_uet` appear with `active_sources >= 2` each.

---

### Task 5: Run Existing Pipeline Tests as Regression Gate

**Files:**
- No changes. Confirms the new seed file didn't break anything.

- [ ] **Step 1: Run the ingestion test suite**

```powershell
.venv/Scripts/python.exe -m pytest tests/ingestion/ -v
```

Expected: all existing tests pass. If anything related to source-registry loading fails, the JSON is likely malformed — fix before committing.

- [ ] **Step 2: VNU-UET regression smoke test**

Confirm VNU-UET pipeline still resolves its sources from the registry:

```powershell
.venv/Scripts/python.exe -c "
from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
p = IngestionPipeline()
srcs = p.registry.get_sources_by_school('vnu_uet')
assert len(srcs) == 2, f'VNU-UET lost sources: {len(srcs)}'
print('VNU-UET registry intact, sources:', [s.source_id for s in srcs])
"
```

If this fails, revert the seed file edit and re-attempt the append.

---

### Task 6: Commit Registry Entries

- [ ] **Step 1: Commit**

```powershell
git add ingestion/registry/seeds/initial_sources.json scripts/verify_hust_registry.py
git commit -m "feat: add HUST 2026 sources to source registry seed"
```

---

### Self-Check Before Proceeding to Plan 03

- `.venv/Scripts/python.exe scripts/verify_hust_registry.py` prints PASS
- `.venv/Scripts/python.exe -m ingestion.main --list-schools` shows both `hust` and `vnu_uet` with ≥2 active sources each
- Both HUST source URLs (`ts.hust.edu.vn/training-cate/nganh-dao-tao-dai-hoc` and `ts.hust.edu.vn/tin-tuc/thong-tin-tuyen-sinh-dai-hoc-chinh-quy-nam-2026`) are confirmed reachable per pre-flight findings
- VNU-UET entries are unchanged (`hust` was appended, not overwritten)
- All existing tests pass
