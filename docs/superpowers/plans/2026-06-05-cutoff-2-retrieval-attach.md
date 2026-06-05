# Cutoff Plan 2 — Retrieval attach `cutoff_history`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `fetch_candidates` gắn lịch sử điểm chuẩn (`cutoff_history`) vào từng `CandidateProgram` bằng MỘT query batch, degrade graceful khi DB/bảng lỗi.

**Architecture:** Hàm mới `fetch_cutoff_history(pairs)` trong `services/retrieval_service.py` (toàn bộ logic nằm trong try/except → `{}` + `logger.warning`, không bao giờ làm fail retrieval); attach một chỗ duy nhất cuối `fetch_candidates`. Đường mock (`ADVISORY_MOCK_CONFLICTS`) return sớm nên không bị ảnh hưởng.

**Tech Stack:** psycopg2 (`WHERE (a,b) IN %s` với tuple-of-tuples), pytest fake-cursor theo pattern `tests/services/test_retrieval_service.py`.

**Phụ thuộc:** Plan 1 (model `CutoffEntry`, bảng 016).

---

### Task 1: `fetch_cutoff_history`

**Files:**
- Modify: `services/retrieval_service.py`
- Test: `tests/services/test_retrieval_service.py` (append)

- [ ] **Step 1: Viết test fail** — append vào `tests/services/test_retrieval_service.py` (file đã có `_FakeCursor`; thêm import nếu thiếu: `from decimal import Decimal`):

```python
def test_fetch_cutoff_history_maps_rows_and_decimal(monkeypatch):
    fake_rows = [
        ("hust", "computer_science", 2025, "thpt_score",
         Decimal("30"), Decimal("28.25"), "https://ts.hust.edu.vn/dc-2025", 5, "TTNV <= 2"),
        ("hust", "computer_science", 2024, "thpt_score",
         Decimal("30"), Decimal("27.10"), "https://ts.hust.edu.vn/dc-2024", 5, None),
    ]
    fake_cursor = _FakeCursor(fake_rows)

    @contextmanager
    def fake_get_cursor(commit=False):
        yield fake_cursor

    monkeypatch.setattr(retrieval_service, "get_cursor", fake_get_cursor)

    history = retrieval_service.fetch_cutoff_history({("hust", "computer_science")})

    entries = history[("hust", "computer_science")]
    assert [e.cutoff_year for e in entries] == [2025, 2024]
    assert entries[0].cutoff_score == 28.25            # Decimal -> float
    assert entries[0].score_scale == 30.0
    assert entries[0].trust_level == 5
    assert entries[0].note == "TTNV <= 2"
    assert "cutoff_records" in fake_cursor.executed_sql


def test_fetch_cutoff_history_empty_pairs_skips_db(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("DB must not be touched for empty pairs")

    monkeypatch.setattr(retrieval_service, "get_cursor", explode)

    assert retrieval_service.fetch_cutoff_history(set()) == {}
    # program_id None bị lọc trước khi chạm DB:
    assert retrieval_service.fetch_cutoff_history({("hust", None)}) == {}


def test_fetch_cutoff_history_degrades_to_empty_on_db_error(monkeypatch):
    @contextmanager
    def broken_get_cursor(commit=False):
        raise RuntimeError("relation cutoff_records does not exist")
        yield  # pragma: no cover

    monkeypatch.setattr(retrieval_service, "get_cursor", broken_get_cursor)

    assert retrieval_service.fetch_cutoff_history({("hust", "computer_science")}) == {}
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/services/test_retrieval_service.py -q`
Expected: FAIL — `AttributeError: ... no attribute 'fetch_cutoff_history'`

- [ ] **Step 3: Implement** — trong `services/retrieval_service.py`: thêm `CutoffEntry` vào import dòng 5 (`from agents.models import CandidateProgram, CutoffEntry, Evidence, StudentProfile`), thêm `Set, Tuple` đã có sẵn `Tuple` trong import typing (dòng 3 → đổi thành `from typing import Any, Dict, List, Optional, Set, Tuple`), rồi thêm hàm sau `build_retrieval_filters`:

```python
def fetch_cutoff_history(
    pairs: Set[Tuple[str, Optional[str]]],
) -> Dict[Tuple[str, str], List[CutoffEntry]]:
    """Batch-load lịch sử điểm chuẩn cho các cặp (school_id, program_id).

    Degrade graceful (EC-18 nền): bảng chưa migrate / DB lỗi / row lệch cột →
    log warning + trả {}; KHÔNG bao giờ làm fail retrieval.
    """
    clean_pairs = {(s, p) for (s, p) in pairs if s and p}
    if not clean_pairs:
        return {}

    sql = """
        SELECT school_id, program_id, cutoff_year, admission_method,
               score_scale, cutoff_score, source_url, source_trust_level, note
        FROM cutoff_records
        WHERE (school_id, program_id) IN %s
        ORDER BY cutoff_year DESC, source_trust_level DESC NULLS LAST
    """
    history: Dict[Tuple[str, str], List[CutoffEntry]] = {}
    try:
        with get_cursor(commit=False) as cur:
            cur.execute(sql, (tuple(clean_pairs),))
            for row in cur.fetchall():
                (school_id, program_id, cutoff_year, admission_method,
                 score_scale, cutoff_score, source_url, trust_level, note) = row
                history.setdefault((school_id, program_id), []).append(
                    CutoffEntry(
                        cutoff_year=cutoff_year,
                        admission_method=admission_method,
                        cutoff_score=float(cutoff_score),
                        score_scale=float(score_scale) if score_scale is not None else None,
                        source_url=source_url or "",
                        trust_level=trust_level,
                        note=note,
                    )
                )
    except Exception as exc:
        logger.warning(
            "fetch_cutoff_history thất bại — tiếp tục KHÔNG có dữ liệu điểm chuẩn: %r", exc
        )
        return {}
    return history
```

- [ ] **Step 4: Chạy test**

Run: `python -m pytest tests/services/test_retrieval_service.py -q`
Expected: PASS (3 test mới + test cũ giữ xanh).

- [ ] **Step 5: Commit**

```bash
git add services/retrieval_service.py tests/services/test_retrieval_service.py
git commit -m "feat: batch fetch_cutoff_history with graceful degradation"
```

---

### Task 2: Attach vào `fetch_candidates`

**Files:**
- Modify: `services/retrieval_service.py` (cuối `fetch_candidates`, trước `return candidates` ở dòng ~164)
- Test: `tests/services/test_retrieval_service.py` (append)

- [ ] **Step 1: Viết test fail** — append:

```python
def test_fetch_candidates_attaches_cutoff_history(monkeypatch):
    monkeypatch.delenv("ADVISORY_MOCK_CONFLICTS", raising=False)
    fake_rows = [
        ("hust", "HUST", 2026, "computer_science", "Khoa hoc May tinh", "Khoa học Máy tính",
         "thpt_score", ["A00", "A01"], {"total": 300}, None, {}, "https://src", 5, 0.9),
    ]
    fake_cursor = _FakeCursor(fake_rows)

    @contextmanager
    def fake_get_cursor(commit=False):
        yield fake_cursor

    monkeypatch.setattr(retrieval_service, "get_cursor", fake_get_cursor)

    from agents.models import CutoffEntry
    entry = CutoffEntry(cutoff_year=2025, admission_method="thpt_score",
                        cutoff_score=27.5, source_url="https://dc", trust_level=5)
    captured = {}

    def fake_history(pairs):
        captured["pairs"] = pairs
        return {("hust", "computer_science"): [entry]}

    monkeypatch.setattr(retrieval_service, "fetch_cutoff_history", fake_history)

    candidates = retrieval_service.fetch_candidates({"admission_year": 2026})

    assert captured["pairs"] == {("hust", "computer_science")}
    assert candidates[0].cutoff_history == [entry]
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/services/test_retrieval_service.py::test_fetch_candidates_attaches_cutoff_history -q`
Expected: FAIL — `assert [] == [entry]` (chưa attach).

- [ ] **Step 3: Implement** — trong `fetch_candidates`, thay `return candidates` (dòng cuối hàm) bằng:

```python
    cutoff_map = fetch_cutoff_history(
        {(c.school_id, c.program_id) for c in candidates if c.program_id}
    )
    for candidate in candidates:
        if candidate.program_id:
            candidate.cutoff_history = cutoff_map.get(
                (candidate.school_id, candidate.program_id), []
            )
    return candidates
```

Lưu ý: test cũ `test_fetch_candidates_maps_rows` vẫn xanh vì `fetch_cutoff_history` thật sẽ chạy
trên fake cursor 14 cột → unpack 9 cột fail BÊN TRONG try → degrade `{}` → history `[]`.
NHƯNG query cutoff (execute thứ hai) sẽ GHI ĐÈ `fake_cursor.executed_sql` — nếu test cũ
assert trên `executed_sql`/`executed_params` sau khi gọi `fetch_candidates`, thêm vào test đó:
`monkeypatch.setattr(retrieval_service, "fetch_cutoff_history", lambda pairs: {})`.

- [ ] **Step 4: Chạy test toàn module + e2e mock-path không vỡ**

Run: `python -m pytest tests/services/test_retrieval_service.py tests/services/test_mock_retrieval.py tests/e2e/test_advisory_flow.py -q`
Expected: PASS toàn bộ (mock path return sớm trước attach; e2e monkeypatch `fetch_candidates` nguyên hàm).

- [ ] **Step 5: Commit**

```bash
git add services/retrieval_service.py tests/services/test_retrieval_service.py
git commit -m "feat: attach cutoff_history to candidates in fetch_candidates"
```

---

### Task 3: Integration round-trip với Docker DB

**Files:**
- Create: `tests/integration/test_cutoff_records_e2e.py`

- [ ] **Step 1: Viết test** (dùng fixture `db_available` sẵn có trong `tests/integration/conftest.py` — tự skip khi DB không chạy):

```python
"""Round-trip: migration 016 → save_cutoff_records → fetch_cutoff_history.

Cần Docker DB: `docker compose up -d db && python -m db.setup_db`.
"""
from ingestion.models.pipeline_models import NormalizedCutoffRecord
from ingestion.storage.db_connection import get_cursor
from ingestion.storage.db_writer import save_cutoff_records
from services.retrieval_service import fetch_cutoff_history

_TEST_URL_A = "integration-test://cutoff/source-a"
_TEST_URL_B = "integration-test://cutoff/source-b"


def _record(year, score, source_url, trust=5):
    return NormalizedCutoffRecord(
        school_id="itest_school", program_id="itest_program",
        program_name_canonical="ITest Program", cutoff_year=year,
        admission_method="thpt_score", score_scale=30.0, cutoff_score=score,
        subject_combinations=["A00"], source_url=source_url, source_trust_level=trust,
    )


def _cleanup():
    with get_cursor() as cur:
        cur.execute("DELETE FROM cutoff_records WHERE school_id = 'itest_school'")


def test_cutoff_roundtrip_upsert_and_fetch(db_available):
    _cleanup()
    try:
        records = [
            _record(2025, 26.20, _TEST_URL_A),
            _record(2025, 26.80, _TEST_URL_B, trust=4),   # nguồn thứ hai cùng (school, program, year)
            _record(2024, 25.90, _TEST_URL_A),
        ]
        assert save_cutoff_records(records) == 3
        # Idempotent: upsert lần 2 không nhân đôi.
        assert save_cutoff_records(records) == 3

        history = fetch_cutoff_history({("itest_school", "itest_program")})
        entries = history[("itest_school", "itest_program")]
        assert len(entries) == 3                                   # per-source coexist (EC-16 nền)
        assert entries[0].cutoff_year == 2025                      # ORDER BY year DESC
        latest_scores = {e.cutoff_score for e in entries if e.cutoff_year == 2025}
        assert latest_scores == {26.20, 26.80}
    finally:
        _cleanup()
```

- [ ] **Step 2: Chạy (DB-less phải skip sạch; có DB phải pass)**

Run: `python -m pytest tests/integration/test_cutoff_records_e2e.py -q`
Expected: SKIP với message remediation khi DB tắt; PASS khi `docker compose up -d db && python -m db.setup_db` đã chạy.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_cutoff_records_e2e.py
git commit -m "test: cutoff records DB round-trip integration"
```
