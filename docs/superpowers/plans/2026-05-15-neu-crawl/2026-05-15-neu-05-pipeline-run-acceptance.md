# NEU Pipeline Run & SQL Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the full ingestion pipeline for `school_id="neu"`, persist canonical records to Postgres, and confirm both SQL acceptance queries pass. Then perform a manual sanity check that the quota conflict is genuine (not a normalization artifact).

**Architecture:** No new code. This plan is execution + verification. The pipeline writes to `canonical_admission_records` using the `ON CONFLICT` upsert introduced in spec `2026-05-15-canonical-records-per-source-design.md`. Two canonical rows per program (one per source) must exist for the conflict signal to fire.

**Tech Stack:** Python, psql (or any PostgreSQL client), `ingestion/storage/db_writer.py`.

**Prerequisite:** Plans 01–04 complete:
- Registry has 2 active NEU sources
- Parser returns ≥3 facts with `program_name` and `quota_raw` from at least the HTML source
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

- [ ] **Step 2: Confirm other school pipelines are unaffected (smoke test)**

If HUST or VNU-UET sources are registered:
```
python -m ingestion.main --school hust --output /tmp/hust_check.json
```

Expected: Exits without error, `/tmp/hust_check.json` contains at least 1 record with a non-null `program_id`. (If no other schools are registered yet, skip this step.)

---

### Task 2: Run the Full Pipeline for NEU

**Files:**
- No code changes. Side effect: writes normalized records to a JSON file.

- [ ] **Step 1: Run the pipeline and capture output**

```
python -m ingestion.main --school neu --output /tmp/neu_records.json
```

Expected log lines (order may vary):
```
INFO ingestion.fetchers: Fetching neu_admission_homepage_2026 ...
INFO ingestion.parsers: Using specialized parser 'neu_admission_page' ...   (or: Generic parser for default_html)
INFO ingestion.fetchers: Fetching neu_proposal_2026 ...
INFO ingestion.parsers: Generic PDF parser ...
INFO ingestion: Pipeline complete: N normalized records
```

If you see `ERROR` for either source, read the traceback and fix before continuing. Common causes:
- Network timeout: retry once; if persistent, check the URL in the registry seed is the confirmed URL from the findings document
- PDF parser crash: verify the PDF URL is accessible with `curl -I <PDF_URL>`
- Normalization crash: run `python scripts/verify_neu_normalization.py` to isolate

- [ ] **Step 2: Inspect the output file**

```python
python - <<'EOF'
import json
data = json.load(open("/tmp/neu_records.json"))
print(f"Total records: {len(data)}")
for r in data[:5]:
    print(
        f"  program_id={r.get('program_id')!r}"
        f"  method={r.get('admission_method')!r}"
        f"  quota={r.get('quota')!r}"
        f"  source={r.get('source_url')!r}"
    )
EOF
```

Expected:
- `Total records` ≥ 6 (≥3 programs × 2 sources)
- `program_id` is non-null for most records
- `quota` is non-null for records from conflict-bearing programs
- Two records with the same `program_id` appear (one per source URL)

If `Total records` is 0, the pipeline ran but produced nothing — go back to Plan 03's diagnostic script and check parser output. If it's low (e.g., 2), check whether only one source produced records.

---

### Task 3: Persist Canonical Records to the Database

**Files:**
- No code changes. Writes to `canonical_admission_records`.

- [ ] **Step 1: Run the pipeline with DB persistence**

```python
python - <<'EOF'
import sys; sys.path.insert(0, ".")
from ingestion.pipeline.ingestion_pipeline import IngestionPipeline
from ingestion.storage.db_writer import save_canonical_records

pipeline = IngestionPipeline()
records = pipeline.run_for_school("neu")
print(f"Pipeline produced {len(records)} records")
count = save_canonical_records(records)
print(f"Saved/upserted {count} records to canonical_admission_records")
EOF
```

Expected: `Saved/upserted N records` where N ≥ 6.

If you see a PostgreSQL error about unknown columns:
- Verify the migration `010_canonical_records_per_source.sql` is applied: `psql -U <DB_USER> -d <DB_NAME> -c "\d canonical_admission_records"` — the `source_url` column must exist.
- Verify the `ON CONFLICT` target in `ingestion/storage/db_writer.py` includes `source_url`.

If you see a unique constraint violation: two records from the same source ended up with the same `(school_id, admission_year, program_id, admission_method, source_url)` key — this means `program_id` is resolving to the same value for two different programs. Debug with `python scripts/verify_neu_normalization.py`.

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
WHERE school_id = 'neu'
  AND admission_year = 2026
ORDER BY program_name_canonical, admission_method, source_url;
```

Expected:
- Rows are present
- Every row has a non-null `source_url`
- Every row has a non-null `quota` JSONB blob
- The `program_name_canonical` column groups rows by program (same value appears for the two source rows of the same program)

If any row shows `source_url = null`, the writer is not setting it correctly — check `save_canonical_records` in `ingestion/storage/db_writer.py` and confirm `record.source_url` is populated from the source's `root_url`.

---

### Task 5: Run SQL Acceptance Query A — Row Count

- [ ] **Step 1: Run Query A**

```sql
SELECT COUNT(*) AS row_count
FROM canonical_admission_records
WHERE school_id = 'neu'
  AND admission_year = 2026;
```

Expected: `row_count > 0`. The spec's reasonable bar is ≥ 10 rows (≥3 programs × 2 sources × ≥2 admission methods average).

If `row_count = 0`: The `save_canonical_records` call succeeded without error but nothing landed in the table. Check that the `school_id` value is exactly `'neu'` in every record — it must not be `'NEU'`, `'Neu'`, or any other variant. Run:

```python
python -c "import sys; sys.path.insert(0,''); from ingestion.registry.source_registry import SourceRegistry; from pathlib import Path; r = SourceRegistry(Path('ingestion/registry/seeds/initial_sources.json')); s = r.get_sources_by_school('neu'); print([x.school_id for x in s])"
```

If `row_count` is lower than expected (e.g., 2 instead of 10): the same row may be upserted repeatedly because records from both sources share the same `(school_id, admission_year, program_id, admission_method, source_url)` key. Verify `source_url` differs between the two NEU sources in the registry.

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
WHERE school_id = 'neu'
  AND admission_year = 2026
  AND quota IS NOT NULL
GROUP BY school_id, admission_year, program_id, admission_method
HAVING COUNT(DISTINCT quota) > 1;
```

Expected: **≥ 1 row returned**. Each returned row is one program-method tuple where at least two canonical rows disagree on quota.

If 0 rows returned, diagnose in this order:

1. **Both rows have the same `source_url`:** The upsert is colliding — the second source overwrites the first. The `ON CONFLICT` target is wrong. Check `db_writer.py`'s `ON CONFLICT` clause includes `source_url`.

2. **Both rows have the same `quota` value:** The quota values are genuinely identical across sources for 2026 — this is the data finding identified as a risk in the spec. Go back to the pre-flight program name mapping table and find a program that actually diverges. If none exist, escalate per the spec's bail-out.

3. **One or both rows have `quota = null`:** Quota extraction failed for that program-source pair. Run the diagnostic script for that source and check `fact.quota_raw`. If `quota_raw` is a digit string like `"600"`, debug the quota parser:
   ```python
   python -c "import sys; sys.path.insert(0,''); from ingestion.normalization.quota_parser import parse_quota; print(parse_quota('600'))"
   ```

4. **`program_id` is null for one source's row:** Normalization failed to map one source's program name. Re-run `python scripts/verify_neu_normalization.py` and fix the missing alias.

---

### Task 7: Manual Sanity Check on Quota Values

- [ ] **Step 1: Read the actual quota JSONB for one conflict-bearing tuple**

From Query B's output, pick one `program_id` + `admission_method` pair that returned `distinct_quota_values > 1`. Run:

```sql
SELECT
    source_url,
    quota
FROM canonical_admission_records
WHERE school_id = 'neu'
  AND admission_year = 2026
  AND program_id = '<program_id_from_query_b>'
  AND admission_method = '<admission_method_from_query_b>';
```

Expected: Two rows. The `quota` JSONB values should differ in their numeric content.

- [ ] **Step 2: Confirm the conflict is genuine**

Inspect the two `quota` JSONB values. They should look like:
```
source 1:  {"value": 600, "quota_type": "exact"}
source 2:  {"value": 550, "quota_type": "exact"}
```

Both should use the same `quota_type`. If one shows `{"value": 600}` and the other shows `{"count": 600, "unit": "students"}`, the conflict is a normalization format difference, not a genuine source disagreement. Fix `quota_parser.py` to produce the same structure for both, then re-run the pipeline and re-check Query B.

If the values differ and both use `"exact"` type — the conflict is genuine. The spec acceptance is satisfied.

---

### Task 8: Document Findings and Commit

**Files:**
- Modify: `docs/ingestion/neu-preflight-findings.md` (append a "Pipeline Execution Findings" section)

- [ ] **Step 1: Append findings to the pre-flight document**

Open `docs/ingestion/neu-preflight-findings.md` and append:

```markdown
## Pipeline Execution Findings — 2026-05-15

**Query A result:** row_count = <N>
**Query B result:** <M> conflict-bearing tuples found

### Conflict-Bearing Programs

| program_id | admission_method | quota (homepage source) | quota (PDF source) |
|------------|-----------------|-------------------------|--------------------|
| finance_banking_neu | thpt_score | 600 | 550 |
| (add all rows from Query B) |

### Sanity Check

Quota values for `<program_id>` / `<method>`:
- Homepage source: `{"value": 600, "quota_type": "exact"}` — matches page text "600 chỉ tiêu"
- PDF source: `{"value": 550, "quota_type": "exact"}` — matches PDF table value "550"

Conclusion: conflict is genuine (not a normalization artifact). Spec acceptance gate PASSED.
```

- [ ] **Step 2: Commit the findings**

```bash
git add docs/ingestion/neu-preflight-findings.md
git commit -m "docs: record NEU pipeline execution findings and SQL acceptance results"
```

---

### Final Self-Check — Spec Acceptance Gate

All of the following must be true:

- [ ] `python -m pytest tests/ingestion/ -v` — all tests pass
- [ ] Query A returns `row_count ≥ 10` (or ≥ 2 at minimum if fewer programs were found)
- [ ] Query B returns ≥ 1 row (at least one conflict-bearing program-method tuple for NEU)
- [ ] Manual sanity check confirms the quota conflict is a genuine source disagreement (not a normalization artifact)
- [ ] Findings documented in `docs/ingestion/neu-preflight-findings.md`
- [ ] HUST regression check unaffected (if HUST is registered): `python -m ingestion.main --school hust` exits without error

If all six are true, this spec is complete. The conflict-aware advisory V1 spec's Slice 1 dataset gate can now incorporate NEU's conflict signal as the third school.
