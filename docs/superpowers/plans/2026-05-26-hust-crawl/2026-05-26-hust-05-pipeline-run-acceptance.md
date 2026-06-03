# HUST Pipeline Run & SQL Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the full ingestion pipeline for `school_id="hust"`, persist canonical records to Postgres, and confirm Query A (row count) passes. Query B (conflict-bearing tuples) is run for observability but is **expected to return zero rows for HUST 2026** per the Plan 01 PROCEED_WITH_CAVEATS override — the cross-school conflict gate is satisfied by VNU-UET alone. Record the actual counts in the findings doc.

**Architecture:** No new code. This plan is execution + verification. The pipeline writes to `canonical_admission_records` using the per-source `ON CONFLICT` upsert that was introduced in spec `2026-05-15-canonical-records-per-source-design.md`. Two canonical rows per program-method (one per source) must exist so the key-alignment invariant from Plan 04 is verifiable end-to-end. The `IngestionPipeline` itself does not call `save_canonical_records` — Task 3 runs a wrapper script that does both, mirroring the structure of `db/reimport.py`.

**Tech Stack:** Python, psql (via `docker compose exec`), `ingestion/storage/db_writer.py`.

**Prerequisite:** Plans 01–04 complete:
- Registry has ≥2 active HUST sources (plus VNU-UET intact)
- Source #1 returns ≥10 facts and Source #2 returns ≥60 facts, all with `program_name`, `quota_raw`, and `admission_method_raw` populated
- Normalization maps all programs to matching `program_id` and `admission_method` across both sources

---

### Task 1: Baseline — Confirm Existing Tests Still Pass

**Files:**
- No changes.

- [ ] **Step 1: Run the ingestion test suite**

```powershell
.venv/Scripts/python.exe -m pytest tests/ingestion/ -v
```

Expected: all green. If any failures appear, fix the regression before proceeding — do not mask it by skipping.

- [ ] **Step 2: VNU-UET regression smoke test (non-destructive)**

Confirm the VNU-UET pipeline still completes end-to-end (no DB write needed — this just exercises fetch/parse/normalize):

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
p = IngestionPipeline()
records = p.run_for_school('vnu_uet')
print(f'VNU-UET produced {len(records)} records')
assert records, 'VNU-UET pipeline regressed — investigate before continuing'
print('OK')
"
```

Expected: prints `VNU-UET produced N records` (N > 0) and `OK`.

---

### Task 2: Run the Full Pipeline for HUST

**Files:**
- No changes. Writes the JSON output as a side effect.

- [ ] **Step 1: Run the pipeline and capture JSON output**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -m ingestion.main --school hust --output docs/ingestion/_hust_pipeline_output.json
```

Expected log lines (order may vary):
```
INFO ingestion: Processing school: hust
INFO ingestion.pipeline.ingestion_pipeline: Starting pipeline for source 'hust_program_listing_2026' ...
INFO ingestion.parsers.parser_dispatcher: Using specialized parser 'hust_programs' (HustProgramParser)
INFO ingestion.pipeline.ingestion_pipeline: Starting pipeline for source 'hust_announcement_html_2026' ...
INFO ingestion.parsers.parser_dispatcher: Using specialized parser 'hust_announcement_html' (HustAnnouncementHtmlParser)   ← if Tier 3 was applied
INFO ingestion: Pipeline complete: N normalized records
```

If you see `ERROR` for either source, read the traceback and fix before continuing. Common causes:
- Network timeout: retry once; if persistent, check the URL in the registry seed.
- HTML parser returns zero facts: re-snapshot the fixture `ingestion/parsers/_fixtures/hust_announcement_2026.html` from the live URL — the article may have been edited. Re-run Plan 03 Task 4 Step 3 against the new fixture.
- Normalization crash: run `python scripts/verify_hust_normalization.py` to isolate which raw name is unmapped.

- [ ] **Step 2: Inspect the output file**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
import json
data = json.load(open('docs/ingestion/_hust_pipeline_output.json', encoding='utf-8'))
print(f'Total records: {len(data)}')

by_source = {}
for r in data:
    by_source.setdefault(r.get('source_url'), 0)
    by_source[r['source_url']] += 1
for src, cnt in by_source.items():
    print(f'  {src!r}: {cnt} records')

print()
print('Sample (first 5):')
for r in data[:5]:
    print(f'  program_id={r.get(\"program_id\")!r}  method={r.get(\"admission_method\")!r}  quota={r.get(\"quota\")!r}  source={r.get(\"source_url\")!r}')
"
```

Expected:
- `Total records` ≥ 70 (~10 from Source #1 plus ~60 from Source #2; pre-flight saw 68 programs on the announcement source)
- Records are distributed across both source URLs (announcement HTML produces roughly 60+, listing produces ~10)
- `program_id` is non-null for most records
- `quota` is non-null for most records
- Two records with the same `program_id` + `admission_method` should appear (one per source URL) for each program that appears in both sources — these are key-aligned pairs; for HUST 2026 the quota values are expected to MATCH (zero divergence), per pre-flight.

If `Total records` is 0, the pipeline ran but produced nothing. Go back to Plan 03's diagnostic and check why the parsers returned no facts.

---

### Task 3: Persist Canonical Records to the Database

**Files:**
- No code changes. Writes to `canonical_admission_records`.

The standard `python -m ingestion.main` only prints JSON; it does not call `save_canonical_records`. Use a wrapper similar to `db/reimport.py`.

- [ ] **Step 1: Run pipeline + writer in one shot**

```powershell
$env:PYTHONIOENCODING="utf-8"; .venv/Scripts/python.exe -c "
import sys
sys.path.insert(0, '.')

# Clear normalizer caches in case JSON dictionaries were edited recently.
import ingestion.normalization.program_mapper as pm
for attr in ('_PROGRAMS_CACHE', '_PROGRAMS_DICT'):
    if hasattr(pm, attr):
        setattr(pm, attr, None)
import ingestion.normalization.method_mapper as mm
for attr in ('_METHODS_CACHE', '_METHOD_DICT'):
    if hasattr(mm, attr):
        setattr(mm, attr, None)
import ingestion.normalization.combo_method_mapper as cmm
if hasattr(cmm, '_RULES_CACHE'):
    cmm._RULES_CACHE = None

from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.storage.db_writer import save_canonical_records

p = IngestionPipeline()
records = p.run_for_school('hust')
print(f'Pipeline produced {len(records)} records')

count = save_canonical_records(records)
print(f'save_canonical_records returned: {count}')
"
```

Expected: `save_canonical_records returned: N` where N matches the pipeline record count (≥6).

If you see a PostgreSQL error about constraint violations or unknown columns, check:
- The migration `010_canonical_records_per_source.sql` is applied (`source_url` column must exist).
- The `ON CONFLICT` target in `db_writer.py` includes `source_url`.

If `save_canonical_records returned: 0` despite a non-zero `len(records)`, the writer logged an exception that it swallowed. Add temporary logging or run with `LOG_LEVEL=DEBUG` and inspect.

- [ ] **Step 2: Confirm rows are in the DB**

```powershell
docker compose exec -T db psql -U postgres -d admission -c "SELECT COUNT(*) FROM canonical_admission_records WHERE school_id='hust';"
```

Expected: count ≥ 70 (matches the writer return value).

---

### Task 4: Spot-Check via SQL

**Files:**
- No changes. Read-only SQL.

- [ ] **Step 1: Run the spot-check query**

```powershell
docker compose exec -T db psql -U postgres -d admission -c "
SELECT
    school_id,
    program_id,
    program_name_canonical,
    admission_method,
    source_url,
    quota
FROM canonical_admission_records
WHERE school_id = 'hust'
  AND admission_year = 2026
ORDER BY program_id, admission_method, source_url
LIMIT 30;
"
```

Expected:
- Rows are present
- Every row has a non-null `source_url`
- Every row has a non-null `quota` JSONB blob
- The `program_name_canonical` column groups rows by program (same value appears for both source rows of the same logical program)
- For at least one program, you can see two rows that differ only in `source_url` (and possibly `quota` value, but per pre-flight, HUST 2026 quotas are expected to match across both sources)

If any row shows `source_url IS NULL`, the writer is not setting it correctly — confirm `record.source_url` is populated upstream.

If `program_id IS NULL` for many rows, normalization is failing for those programs — return to Plan 04 Task 5.

---

### Task 5: Run SQL Acceptance Query A — Row Count

- [ ] **Step 1: Run Query A**

```powershell
docker compose exec -T db psql -U postgres -d admission -c "
SELECT COUNT(*) AS row_count
FROM canonical_admission_records
WHERE school_id = 'hust'
  AND admission_year = 2026;
"
```

Expected: `row_count ≥ 70` for HUST 2026 (≈10 listing rows + ≈60 announcement rows).

Diagnosis if low:
- `row_count = 0`: The `save_canonical_records` call succeeded without error but nothing landed in the table. Check `school_id` value in the records is exactly `'hust'` (not `'HUST'`, not `'bach-khoa'`).
- `row_count` lower than the JSON output count (e.g., 60 instead of 70): rows are being upserted onto the same key because `source_url` is identical between sources for the same logical program — should not happen if both registry entries have different `root_url` values. Check that `record.source_url` reflects the source's actual URL.

---

### Task 6: Run SQL Acceptance Query B — Conflict-Bearing Tuples

Per the Plan 01 PROCEED_WITH_CAVEATS override, HUST 2026 is **expected to return zero** conflict-bearing tuples (pre-flight saw 6/6 published-quota pairs matching across the two sources). This task runs Query B for observability and records the actual count, but the cross-school acceptance gate is met by VNU-UET alone — see Final Self-Check.

- [ ] **Step 1: Run Query B**

```powershell
docker compose exec -T db psql -U postgres -d admission -c "
SELECT
    school_id,
    admission_year,
    program_id,
    admission_method,
    COUNT(DISTINCT quota::text) AS distinct_quota_values,
    array_agg(source_url ORDER BY source_url) AS sources
FROM canonical_admission_records
WHERE school_id = 'hust'
  AND admission_year = 2026
  AND quota IS NOT NULL
GROUP BY school_id, admission_year, program_id, admission_method
HAVING COUNT(DISTINCT quota::text) > 1
ORDER BY program_id, admission_method;
"
```

Expected: **0 rows returned for HUST 2026** (pre-flight predicted full agreement). Capture the actual count for the findings doc. Any non-zero number is a surprise — investigate it, but it does not block acceptance.

If unexpectedly **>0 rows**, that means HUST quotas have drifted between the two sources since pre-flight (2026-05-26). Inspect the divergent tuples in Task 7 and confirm whether the new conflict is genuine (might mean the data has changed and a re-do of Plan 01's mapping is warranted).

If unexpectedly **>0 rows in a way that looks like an artifact** (not a real source disagreement), diagnose in this order:

1. **Both rows have the same `source_url`:** The upsert collided — second source overwrote first. The `ON CONFLICT` target is wrong, or the registry has both sources pointing to the same URL. Check both with:
   ```sql
   SELECT source_url, COUNT(*) FROM canonical_admission_records
   WHERE school_id='hust' GROUP BY source_url;
   ```

2. **One or both rows have `quota IS NULL`:** Quota extraction failed for that program/source. Run Plan 03's diagnostic for that source and check `fact.quota_raw`. Debug `quota_parser` with:
   ```powershell
   .venv/Scripts/python.exe -c "from ingestion.normalization.quota_parser import parse_quota; print(parse_quota('120'))"
   ```

3. **`admission_method` is NULL for one source's row but not the other:** The Plan 03 Task 2 fix didn't take effect, OR Plan 04's method mapper isn't resolving both raw method strings to the same canonical code. Re-run `python scripts/verify_hust_normalization.py`.

4. **`program_id` is NULL or differs between sources:** Normalization failed to map one source's program name. Re-run `python scripts/verify_hust_normalization.py` and fix missing aliases.

For comparison, also run Query B against VNU-UET to confirm the cross-school gate (≥3 conflict-bearing tuples) is satisfied:

```powershell
docker compose exec -T db psql -U postgres -d admission -c "
SELECT
    school_id,
    program_id,
    admission_method,
    COUNT(DISTINCT quota::text) AS distinct_quota_values
FROM canonical_admission_records
WHERE admission_year = 2026
  AND quota IS NOT NULL
GROUP BY school_id, program_id, admission_method
HAVING COUNT(DISTINCT quota::text) > 1
ORDER BY school_id, program_id;
"
```

Expected: ≥3 rows total across both schools (VNU-UET should supply all of them).

---

### Task 7: Manual Sanity Check on Quota Values

**Run this task only if Query B returned ≥1 row for HUST.** Per pre-flight, HUST 2026 is expected to return 0 conflict-bearing tuples; skip to Task 8 in that case (and record the zero count there).

If HUST Query B returned >0 rows (a surprise), inspect them to determine whether the divergence is genuine (real source disagreement) or artifactual (normalization/parsing bug). The steps below apply to that case.

- [ ] **Step 1: Read the actual quota JSONB for one conflict-bearing tuple**

From Query B's output, pick one `program_id` + `admission_method` pair that returned `distinct_quota_values > 1`. Run:

```powershell
docker compose exec -T db psql -U postgres -d admission -c "
SELECT source_url, quota
FROM canonical_admission_records
WHERE school_id = 'hust'
  AND admission_year = 2026
  AND program_id = '<PROGRAM_ID_FROM_QUERY_B>'
  AND admission_method = '<METHOD_FROM_QUERY_B>';
"
```

Expected: two rows. `quota` for row 1 (program listing) and row 2 (announcement HTML) should differ in their numeric value (since Query B grouped on `distinct_quota_values > 1`).

- [ ] **Step 2: Confirm the conflict is genuine — not a normalization artifact**

Inspect the two `quota` JSONB blobs:

```
source 1 (program listing)     : {"value": 150, "quota_type": "exact"}
source 2 (announcement HTML)   : {"value": 120, "quota_type": "exact"}
```

Both should use the same `quota_type`. If one shows `{"value": 150}` and the other `{"count": 150, "unit": "students"}`, the conflict is a normalization format difference, not a genuine source disagreement. Fix `quota_parser.py` to produce the same JSONB shape for both, then re-run from Task 3.

- [ ] **Step 3: Confirm the conflict is genuine — not a semantic-measurement mismatch (the VNU-UET trap)**

Cross-check against `docs/ingestion/hust-preflight-findings.md` "Semantic-Measurement Decision" line:
- If pre-flight decided both sources publish program totals, both numbers above must be program totals.
- If pre-flight decided both sources publish method-level quotas for the same method, both numbers must be for that same method.

Open the live announcement article and the live listing page for this exact program. Confirm:
- The listing's `Chỉ tiêu tuyển sinh: 150` is the **same kind** of number as the announcement's `120` (both are 2026 program totals per pre-flight's "Semantic-Measurement Decision" — see findings).
- If on inspection they turn out to be different things (e.g., listing is "total all methods", announcement is "THPT method only"), the conflict is fabricated. Roll back to Plan 01 and re-do Step 4 of Plan 01 — the semantic-measurement check failed silently.

If the numbers are like-for-like, the conflict is real and a surprise (pre-flight expected zero) — record it in Task 8 and consider whether HUST has published new data since 2026-05-26.

---

### Task 8: Document Findings and Commit

**Files:**
- Modify: `docs/ingestion/hust-preflight-findings.md` (append a "Pipeline Execution Findings" section)

- [ ] **Step 1: Append findings to the pre-flight document**

Open `docs/ingestion/hust-preflight-findings.md` and append:

```markdown
## Pipeline Execution Findings — <DATE>

**Query A result (HUST):** row_count = <N>
**Query B result (HUST):** <M> conflict-bearing tuples found  (pre-flight expectation: 0)
**Query B result (cross-school):** <K> conflict-bearing tuples across HUST + VNU-UET combined (spec gate: ≥3)

### Conflict-Bearing Programs (HUST)

If <M> > 0, record each unexpected divergence here:

| program_id | admission_method | quota (listing source) | quota (announcement source) | sources                                                                                |
|------------|------------------|------------------------|-----------------------------|----------------------------------------------------------------------------------------|
| <pid>      | <method>         | <N>                    | <M>                         | ts.hust.edu.vn/training-cate/... ; ts.hust.edu.vn/tin-tuc/...thong-tin-tuyen-sinh...   |
| (all rows from Query B)

If <M> == 0: write "No HUST conflict tuples surfaced — matches pre-flight expectation."

### Sanity Check (only if HUST <M> > 0)

Quota values for `<program_id>` / `<method>`:
- Listing source       : `{"value": <N>, "quota_type": "exact"}` — matches listing card "Chỉ tiêu tuyển sinh: <N>"
- Announcement source  : `{"value": <M>, "quota_type": "exact"}` — matches announcement table row "<program_name>" → "Chỉ tiêu dự kiến: <M>"

Semantic-measurement re-confirmation:
- Pre-flight decision: <copy the line from "Semantic-Measurement Decision" section>
- Inspection of these specific rows: <PASS — both are program totals> OR <FAIL — different measurements>

Conclusion: <"Conflict is genuine — HUST quotas have drifted since 2026-05-26"> OR <"Conflict is artifactual — fix and re-run"> OR <"Expected zero conflicts confirmed — Query B == 0">. Spec acceptance gate met via cross-school Query B (HUST + VNU-UET combined ≥3).
```

If the cross-school Query B (HUST + VNU-UET combined) returns fewer than 3 rows, append a "Bail-out applied" section and roll back to investigate why VNU-UET's conflict count regressed — the spec gate now depends on VNU-UET alone supplying ≥3 conflicts.

- [ ] **Step 2: Commit the findings**

```powershell
git add docs/ingestion/hust-preflight-findings.md
git commit -m "docs: record HUST pipeline execution findings and SQL acceptance results"
```

- [ ] **Step 3: Clean up the temporary working file (optional)**

```powershell
Remove-Item docs/ingestion/_hust_pipeline_output.json -ErrorAction SilentlyContinue
Remove-Item docs/ingestion/_hust_raw_facts.txt -ErrorAction SilentlyContinue
```

These intermediate files are listed in `.gitignore` only if you add them; they're not required artifacts.

---

### Final Self-Check — Spec Acceptance Gate

All of the following must be true:

- [ ] `.venv/Scripts/python.exe -m pytest tests/ingestion/ -v` — all tests pass
- [ ] Query A returns `row_count ≥ 70` for HUST (~10 listing + ~60 announcement)
- [ ] Query B returns 0 rows for HUST 2026 — matches pre-flight expectation per the PROCEED_WITH_CAVEATS override. If non-zero, Task 7 sanity check confirmed whether the divergence is genuine or artifactual.
- [ ] Cross-school Query B (HUST + VNU-UET combined) returns **≥3 rows** — the spec's hard acceptance gate, satisfied by VNU-UET alone for 2026.
- [ ] Findings documented in `docs/ingestion/hust-preflight-findings.md`
- [ ] VNU-UET pipeline still produces records (regression smoke test in Task 1 Step 2 passed)

If all six are true, this spec is complete. The conflict-aware advisory V1 spec's Slice 1 dataset gate has VNU-UET supplying the ≥3 cross-school conflicts; HUST contributes baseline coverage but no divergence for 2026 (the accepted PROCEED_WITH_CAVEATS outcome).
