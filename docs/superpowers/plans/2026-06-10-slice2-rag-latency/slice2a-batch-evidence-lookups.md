# Slice 2a — Batch Conflict Evidence DB Lookups — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one-DB-connection-per-evidence-option lookup in
`package_evidence` with a single batched query per conflict record.

**Architecture:** `package_evidence` partitions a record's options into mock
(skip DB) and DB-backed. For the DB-backed set it runs **one**
`source_url = ANY(%s)` query inside a single `get_cursor`, builds a
`{source_url: fetched_at}` map, and assigns `fetched_at` per option. All-mock
records open no cursor at all.

**Tech Stack:** Python, psycopg2, pytest (mocked `get_cursor` — no live DB
needed for this slice).

**Spec:** `docs/superpowers/specs/2026-06-10-slice2-rag-latency-design.md` §2a

---

### Task 1: Batch the `fetched_at` lookup into one query per record

**Files:**
- Modify: `services/conflict/evidence_agent.py` (replace `_enrich_from_db` + `package_evidence`)
- Test: `tests/services/conflict/test_evidence_agent.py`

- [ ] **Step 1: Write the failing test (one connection + one query for K options)**

Add to `tests/services/conflict/test_evidence_agent.py`:

```python
def test_package_evidence_batches_db_lookup_into_one_query(monkeypatch):
    candidates = [
        candidate("https://uet.vnu.edu.vn/a", 120),
        candidate("https://vnu.edu.vn/b.pdf", 150),
    ]
    record = detect_quota_conflicts(candidates)[0]

    counts = {"cursor": 0, "execute": 0}

    class Cursor:
        def execute(self, sql, params=None):
            counts["execute"] += 1
            assert "= ANY(" in sql  # batched, not per-option

        def fetchall(self):
            return [
                ("https://uet.vnu.edu.vn/a", "2026-01-01"),
                ("https://vnu.edu.vn/b.pdf", "2026-01-02"),
            ]

    class CursorContext:
        def __enter__(self):
            counts["cursor"] += 1
            return Cursor()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "services.conflict.evidence_agent.get_cursor",
        lambda commit=False: CursorContext(),
    )

    options = package_evidence(record, candidates)

    assert counts["cursor"] == 1   # one connection for the whole record
    assert counts["execute"] == 1  # one query, not one per option
    assert {o.source_url: o.fetched_at for o in options} == {
        "https://uet.vnu.edu.vn/a": "2026-01-01",
        "https://vnu.edu.vn/b.pdf": "2026-01-02",
    }
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `.venv/bin/python -m pytest tests/services/conflict/test_evidence_agent.py::test_package_evidence_batches_db_lookup_into_one_query -v`
Expected: FAIL — current code opens one cursor per option (`counts["cursor"] == 2`) and calls `fetchone` (so `fetchall` is never reached / `execute` count is 2).

- [ ] **Step 3: Rewrite `evidence_agent.py` to batch**

Replace `_enrich_from_db` and `package_evidence` in
`services/conflict/evidence_agent.py` (keep `_candidate_by_source` and
`_is_mock_source` unchanged):

```python
def _batch_fetched_at(source_urls: List[str], record: ConflictRecord) -> Dict[str, object]:
    """One query mapping source_url -> fetched_at for this record's school/year.

    Drops the per-option LIMIT 1, so a source_url with several canonical rows can
    return several rows; the first wins (fetched_at is a property of the source
    document, consistent across that URL's rows)."""
    sql = """
        SELECT car.source_url, rd.fetched_at
        FROM canonical_admission_records car
        LEFT JOIN extracted_facts ef ON ef.id = car.extracted_fact_id
        LEFT JOIN raw_documents rd ON rd.id = ef.raw_document_id
        WHERE car.source_url = ANY(%s)
          AND car.school_id = %s
          AND car.admission_year = %s
    """
    mapping: Dict[str, object] = {}
    with get_cursor(commit=False) as cur:
        cur.execute(sql, (list(source_urls), record.school_id, record.admission_year))
        for source_url, fetched_at in cur.fetchall():
            mapping.setdefault(source_url, fetched_at)  # first row wins per url
    return mapping


def package_evidence(
    record: ConflictRecord,
    raw_candidates: List[CandidateProgram],
) -> List[EvidenceOption]:
    candidates_by_source = _candidate_by_source(raw_candidates)

    # Partition: mock options skip the DB; real options get ONE batched lookup.
    db_urls = [
        option.source_url
        for option in record.options
        if not _is_mock_source(
            option.source_url, candidates_by_source.get(option.source_url)
        )
    ]

    fetched_map: Dict[str, object] = {}
    if db_urls:  # all-mock record → no cursor opened at all
        try:
            fetched_map = _batch_fetched_at(db_urls, record)
        except Exception:
            fetched_map = {}  # DB down → leave options un-enriched, as before

    packaged: List[EvidenceOption] = []
    for option in record.options:
        candidate = candidates_by_source.get(option.source_url)
        if _is_mock_source(option.source_url, candidate):
            packaged.append(option)
            continue
        if option.source_url in fetched_map:
            option.fetched_at = fetched_map[option.source_url]
        packaged.append(option)
    return packaged
```

- [ ] **Step 4: Run the new test, verify it passes**

Run: `.venv/bin/python -m pytest tests/services/conflict/test_evidence_agent.py::test_package_evidence_batches_db_lookup_into_one_query -v`
Expected: PASS

- [ ] **Step 5: Update the existing "enrichment missing" fake to expose `fetchall`**

The batched code calls `fetchall()` instead of `fetchone()`. Update the fake
`Cursor` in `test_package_evidence_keeps_options_when_db_enrichment_missing`:

```python
    class Cursor:
        def execute(self, *args, **kwargs):
            return None

        def fetchall(self):
            return []
```

(Delete the now-unused `fetchone` method.)

- [ ] **Step 6: Run the whole evidence-agent test file**

Run: `.venv/bin/python -m pytest tests/services/conflict/test_evidence_agent.py -v`
Expected: PASS — including `test_package_evidence_uses_candidate_evidence_for_mock_sources` (all-mock record opens no cursor, so its `fail_cursor` is never called).

- [ ] **Step 7: Run the conflict suite to catch integration callers**

Run: `.venv/bin/python -m pytest tests/services/conflict -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add services/conflict/evidence_agent.py tests/services/conflict/test_evidence_agent.py
git commit -m "feat(conflict): batch evidence fetched_at lookup into one query per record"
```
