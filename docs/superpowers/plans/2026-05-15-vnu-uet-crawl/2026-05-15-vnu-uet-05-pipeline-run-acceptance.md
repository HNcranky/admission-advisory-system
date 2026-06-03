# VNU-UET Pipeline Run & SQL Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the full ingestion pipeline for `school_id="vnu_uet"`, persist canonical records to Postgres, and confirm both SQL acceptance queries pass. Then perform a manual sanity check that the quota conflict is genuine (not a normalization artifact).

**Architecture:** No new code. This plan is execution + verification. The pipeline writes to `canonical_admission_records` using the `ON CONFLICT` upsert that was introduced in spec `2026-05-15-canonical-records-per-source-design.md`. Two canonical rows per program (one per source) must exist for the conflict signal to fire.

**Tech Stack:** Python, psql (or any PostgreSQL client), `ingestion/storage/db_writer.py`.

**Prerequisite:** Plans 01–04 complete:
- Registry has 2 active VNU-UET sources
- Parser returns ≥3 facts with program_name and quota_raw from at least the HTML source
- Normalization maps all conflict-bearing programs to matching `program_id` across both sources

---

### Task 1: Baseline — Confirm Existing Tests Still Pass

**Files:**
- No changes.

- [ ] **Step 1: Run the ingestion test suite**

```
python -m pytest tests/ingestion/ -v
```

Expected: All tests pass. If any fail, fix the regression before proceeding — do not mask it by skipping.

- [ ] **Step 2: Confirm the HUST pipeline is unaffected (smoke test)**

If there is a HUST source in the registry:
```
python -m ingestion.main --school hust --output /tmp/hust_check.json
```

Expected: Exits without error, `/tmp/hust_check.json` contains at least 1 record with a non-null `program_id`. (If HUST isn't registered yet, skip this step — it's not a blocker.)

---

### Task 2: Run the Full Pipeline for VNU-UET

**Files:**
- No code changes. Side effect: writes to the database.

- [ ] **Step 1: Run the pipeline and capture output**

```
python -m ingestion.main --school vnu_uet --output /tmp/vnu_uet_records.json
```

Expected log lines (order may vary):
```
INFO ingestion.fetchers: Fetching vnu_uet_admission_homepage_2026 ...
INFO ingestion.parsers: Using specialized parser 'vnu_uet_admission_page' ...   (or: Generic parser for default_html)
INFO ingestion.fetchers: Fetching vnuhn_proposal_pdf_2026 ...
INFO ingestion.parsers: Generic PDF parser ...
INFO ingestion: Pipeline complete: N normalized records
```

If you see `ERROR` for either source, read the traceback and fix before continuing. Common causes:
- Network timeout: retry once; if persistent, check the URL in the registry seed is correct
- PDF parser crash: verify the PDF URL is accessible with `curl -I <PDF_URL>`
- Normalization crash: run `python scripts/verify_vnu_uet_normalization.py` to isolate

- [ ] **Step 2: Inspect the output file**

```
python -c "
import json
data = json.load(open('/tmp/vnu_uet_records.json'))
print(f'Total records: {len(data)}')
for r in data[:5]:
    print(f'  program_id={r.get(\"program_id\")!r}  method={r.get(\"admission_method\")!r}  quota={r.get(\"quota\")!r}  source={r.get(\"source_url\")!r}')
"
```

Expected:
- `Total records` ≥ 6 (≥3 programs × 2 sources)
- `program_id` is non-null for most records
- `quota` is non-null for records from conflict-bearing programs
- Two records with the same `program_id` should appear (one per source URL)

If `Total records` is 0, the pipeline ran but produced nothing — go back to Plan 03's diagnostic script and check parser output.

---

### Task 3: Persist Canonical Records to the Database

**Files:**
- No code changes. Writes to `canonical_admission_records`.

- [ ] **Step 1: Run the database writer on the output**

```python
python - <<'EOF'
import sys, json
sys.path.insert(0, ".")
from ingestion.storage.db_writer import save_canonical_records
from ingestion.models.pipeline_models import NormalizedAdmissionRecord

with open("/tmp/vnu_uet_records.json") as f:
    raw = json.load(f)

records = [NormalizedAdmissionRecord(**r) for r in raw]
count = save_canonical_records(records)
print(f"Saved/upserted {count} canonical records for vnu_uet")
EOF
```

Expected: `Saved/upserted N canonical records for vnu_uet` where N ≥ 6.

If you see a PostgreSQL error about unknown columns or constraint violations, check:
- The migration `010_canonical_records_per_source.sql` is applied (column `source_url` exists)
- The `ON CONFLICT` target in `db_writer.py` includes `source_url`

Alternatively, run the full pipeline with DB persistence directly:

```python
python - <<'EOF'
import sys; sys.path.insert(0, ".")
from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.storage.db_writer import save_canonical_records

pipeline = IngestionPipeline()
records = pipeline.run_for_school("vnu_uet")
print(f"Pipeline produced {len(records)} records")
count = save_canonical_records(records)
print(f"Saved/upserted {count} records")
EOF
```

---

### Task 4: Spot-Check via SQL

**Files:**
- No changes. Read-only SQL.

- [ ] **Step 1: Run the spot-check query**

Connect to psql and run:

```sql
SELECT
    school_id,
    program_name_canonical,
    admission_method,
    source_url,
    quota
FROM canonical_admission_records
WHERE school_id = 'vnu_uet'
  AND admission_year = 2026
ORDER BY program_name_canonical, admission_method, source_url;
```

Expected:
- Rows are present
- Every row has a non-null `source_url`
- Every row has a non-null `quota` JSONB blob
- The `program_name_canonical` column groups rows by program (same value appears for both source rows of the same program)

If any row shows `source_url = null`, the writer is not setting it correctly — check `save_canonical_records` in `ingestion/storage/db_writer.py` and confirm `record.source_url` is populated.

---

### Task 5: Run SQL Acceptance Query A — Row Count

- [ ] **Step 1: Run Query A**

```sql
SELECT COUNT(*) AS row_count
FROM canonical_admission_records
WHERE school_id = 'vnu_uet'
  AND admission_year = 2026;
```

Expected: `row_count > 0`. The spec's reasonable bar is ≥ 10 rows (≥3 programs × 2 sources × ≥2 methods average).

If `row_count = 0`: The `save_canonical_records` call succeeded without error but nothing landed in the table. Check the `school_id` value — it must be exactly `'vnu_uet'` (not `'uet'`, not `'vnu-uet'`).

If `row_count` is lower than expected (e.g. 2 instead of 10): The same row is being upserted repeatedly because source rows are getting the same `(school_id, admission_year, program_id, admission_method, source_url)` key. Check that `source_url` is distinct between the two sources for the same logical program.

---

### Task 6: Run SQL Acceptance Query B — Conflict-Bearing Tuples

This is the spec's hard acceptance gate.

- [ ] **Step 1: Run Query B**

```sql
SELECT
    school_id,
    admission_year,
    program_id,
    admission_method,
    COUNT(DISTINCT quota) AS distinct_quota_values
FROM canonical_admission_records
WHERE school_id = 'vnu_uet'
  AND admission_year = 2026
  AND quota IS NOT NULL
GROUP BY school_id, admission_year, program_id, admission_method
HAVING COUNT(DISTINCT quota) > 1;
```

Expected: **≥ 1 row returned**. Each returned row is one program-method tuple where at least two canonical rows disagree on quota.

If 0 rows returned, diagnose in this order:

1. **Both rows have the same `source_url`:** The upsert is colliding — second source overwrites first. The `ON CONFLICT` target is wrong. Check `db_writer.py`'s `ON CONFLICT` clause.

2. **Both rows have the same `quota` value:** The quota values are genuinely identical across sources for 2026 — this is a data finding, not a bug. Go back to the pre-flight program name mapping table and find a program that actually diverges.

3. **One or both rows have `quota = null`:** Quota extraction failed for that program-source pair. Run the diagnostic script for that source and check `fact.quota_raw`. If `quota_raw` is a string like `"120"`, the `quota_parser.py` should convert it — debug with:
   ```python
   python -c "import sys; sys.path.insert(0,''); from ingestion.normalization.quota_parser import parse_quota; print(parse_quota('120'))"
   ```

4. **`program_id` is null for one source's row:** Normalization failed to map one source's program name. Re-run `python scripts/verify_vnu_uet_normalization.py` and fix the missing alias.

---

### Task 7: Manual Sanity Check on Quota Values

- [ ] **Step 1: Read the actual quota JSONB for one conflict-bearing tuple**

From Query B's output, pick one `program_id` + `admission_method` pair that returned `distinct_quota_values > 1`. Run:

```sql
SELECT
    source_url,
    quota
FROM canonical_admission_records
WHERE school_id = 'vnu_uet'
  AND admission_year = 2026
  AND program_id = '<program_id_from_query_b>'
  AND admission_method = '<admission_method_from_query_b>';
```

Expected: Two rows. `quota` for row 1 and row 2 should differ in their numeric value.

- [ ] **Step 2: Confirm the conflict is genuine**

Inspect the two `quota` JSONB values:

```
source 1:  {"value": 150, "quota_type": "exact"}
source 2:  {"value": 120, "quota_type": "exact"}
```

Both should use the same `quota_type`. If one shows `{"value": 150}` and the other shows `{"count": 150, "unit": "students"}` — the conflict is a normalization format difference, not a genuine source disagreement. Fix `quota_parser.py` to produce the same structure for both, then re-run the pipeline and re-check.

If the values differ and both use `"exact"` type, the conflict is genuine. The spec acceptance is satisfied.

---

### Task 8: Document Findings and Commit

**Files:**
- Modify: `docs/ingestion/vnu-uet-preflight-findings.md` (add a "Findings" appendix)

- [ ] **Step 1: Append findings to the pre-flight document**

Open `docs/ingestion/vnu-uet-preflight-findings.md` and append:

```markdown
## Pipeline Execution Findings — 2026-05-15

**Query A result:** row_count = <N>
**Query B result:** <M> conflict-bearing tuples found

### Conflict-Bearing Programs

| program_id | admission_method | quota (homepage source) | quota (PDF source) |
|------------|-----------------|-------------------------|--------------------|
| computer_science_uet | competency_test | 150 | 120 |
| (add all rows from Query B) |

### Sanity Check

Quota values for `<program_id>` / `<method>`:
- Homepage source: `{"value": 150, "quota_type": "exact"}` — matches page text "150 chỉ tiêu"
- PDF source: `{"value": 120, "quota_type": "exact"}` — matches PDF table value "120"

Conclusion: conflict is genuine (not a normalization artifact). Spec acceptance gate PASSED.
```

- [ ] **Step 2: Commit the findings**

```bash
git add docs/ingestion/vnu-uet-preflight-findings.md
git commit -m "docs: record VNU-UET pipeline execution findings and SQL acceptance results"
```

---

### Final Self-Check — Spec Acceptance Gate

All of the following must be true:

- [ ] `python -m pytest tests/ingestion/ -v` — all tests pass
- [ ] Query A returns `row_count ≥ 10` (or ≥ 2 at minimum if fewer programs were found)
- [ ] Query B returns ≥ 1 row (at least one conflict-bearing program-method tuple)
- [ ] Manual sanity check confirms the quota conflict is a genuine source disagreement
- [ ] Findings documented in `docs/ingestion/vnu-uet-preflight-findings.md`

If all five are true, this spec is complete. The conflict-aware advisory V1 spec's Slice 1 dataset gate can now incorporate VNU-UET's conflict signal.
