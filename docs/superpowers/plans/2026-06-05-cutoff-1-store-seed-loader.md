# Cutoff Plan 1 — Store, models, seed curated & loader CLI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bảng `cutoff_records` per-source + models hai phía (ingestion/agents) + hàm ghi upsert + seed điểm chuẩn curated 2023–2025 (HUST, VNU-UET, thang 30) + CLI nạp seed validate-atomic.

**Architecture:** Mirror đúng pattern hiện có — migration idempotent kiểu `005/010`, model Pydantic v2 trong `pipeline_models.py`/`agents/models.py`, `save_cutoff_records` theo khuôn `save_canonical_records` (get_cursor + ON CONFLICT per-source), CLI theo khuôn `ingest_national`. `admission_method` trong cutoff_records lưu MÃ canonical (`thpt_score`) — khác convention display-name của `canonical_admission_records`.

**Tech Stack:** Python 3.12, Pydantic v2, psycopg2, pytest (fake cursor — không cần DB cho unit).

---

### Task 1: Migration 016 — bảng `cutoff_records`

**Files:**
- Create: `db/migrations/016_cutoff_records.sql`

- [x] **Step 1: Viết migration**

```sql
-- Điểm chuẩn lịch sử per-source (Giai đoạn 2 — EC-14/15/16/18).
-- admission_method lưu MÃ canonical ('thpt_score'...), KHÁC convention
-- display-name của canonical_admission_records. Unique key per-source
-- mirror migration 010 để hai nguồn cùng tồn tại thành hai row (EC-16).
CREATE TABLE IF NOT EXISTS cutoff_records (
    id                     SERIAL PRIMARY KEY,
    school_id              TEXT NOT NULL,
    program_id             TEXT,
    program_name_canonical TEXT,
    program_name_raw       TEXT,
    cutoff_year            INTEGER NOT NULL,
    admission_method       TEXT NOT NULL,
    score_scale            NUMERIC,
    cutoff_score           NUMERIC NOT NULL,
    subject_combinations   JSONB,
    note                   TEXT,
    source_url             TEXT NOT NULL,
    source_trust_level     INTEGER,
    confidence_score       REAL,
    ingested_at            TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (school_id, cutoff_year, program_id, admission_method, source_url)
);

CREATE INDEX IF NOT EXISTS idx_cutoff_school_program
    ON cutoff_records (school_id, program_id, admission_method);

CREATE INDEX IF NOT EXISTS idx_cutoff_school_year
    ON cutoff_records (school_id, cutoff_year);
```

- [x] **Step 2: Chạy migration với Docker DB (nếu DB đang chạy; nếu không, integration test ở Plan 2 sẽ phủ)**

Run: `docker compose up -d --wait db && python -m db.setup_db`
Expected: log liệt kê `016_cutoff_records.sql` được apply, không lỗi. (`db/setup_db.py:63` chạy `sorted(migrations_dir.glob("*.sql"))` nên 016 tự được nhặt.)

- [x] **Step 3: Commit**

```bash
git add db/migrations/016_cutoff_records.sql
git commit -m "feat: cutoff_records table for historical benchmark scores (migration 016)"
```

---

### Task 2: Models hai phía

**Files:**
- Modify: `agents/models.py` (thêm `Literal` vào import; thêm 2 class sau `Evidence`; thêm field vào `CandidateProgram`, `RankedRecommendation`)
- Modify: `ingestion/models/pipeline_models.py` (thêm 2 class cuối file)
- Test: `tests/test_state.py` (chạy lại để chắc model cũ không vỡ — không sửa)

- [x] **Step 1: Viết test cho model mới**

Create `tests/agents/test_cutoff_models.py`:

```python
from agents.models import CandidateProgram, CutoffAssessment, CutoffEntry, RankedRecommendation


def test_cutoff_entry_minimal():
    e = CutoffEntry(
        cutoff_year=2025, admission_method="thpt_score",
        cutoff_score=28.25, source_url="https://ts.hust.edu.vn/x",
    )
    assert e.score_scale is None and e.trust_level is None and e.note is None


def test_candidate_program_defaults_empty_cutoff_history():
    c = CandidateProgram(
        candidate_id="hust:2026:cs:thpt_score", school_id="hust", school_name="HUST",
        admission_year=2026, program_name="KHMT",
    )
    assert c.cutoff_history == []


def test_ranked_recommendation_accepts_assessment():
    a = CutoffAssessment(score_fit="borderline", reference_year=2025, margin=0.05)
    r = RankedRecommendation(
        candidate_id="c", band="match", score=0.6, summary="s", cutoff_assessment=a,
    )
    assert r.cutoff_assessment.score_fit == "borderline"
    assert r.cutoff_assessment.latest_values == []
```

- [x] **Step 2: Chạy test để thấy fail**

Run: `python -m pytest tests/agents/test_cutoff_models.py -q`
Expected: FAIL — `ImportError: cannot import name 'CutoffEntry'`

- [x] **Step 3: Sửa `agents/models.py`**

Đổi dòng 1 thành:

```python
from typing import Any, Dict, List, Literal, Optional
```

Thêm sau class `Evidence` (sau dòng 26):

```python
class CutoffEntry(BaseModel):
    """Một dòng điểm chuẩn lịch sử của (trường, chương trình) từ một nguồn."""
    cutoff_year: int
    admission_method: str          # mã canonical: 'thpt_score'...
    cutoff_score: float
    score_scale: Optional[float] = None
    source_url: str
    trust_level: Optional[int] = None
    note: Optional[str] = None


class CutoffAssessment(BaseModel):
    """Kết quả đối chiếu điểm hồ sơ với điểm chuẩn lịch sử (EC-14/15/16/18).

    Đặt ở agents.models (không phải services/cutoff) để tránh vòng import:
    services/cutoff/assessment.py import CutoffEntry từ đây."""
    score_fit: Literal["above", "borderline", "below", "uncertain"]
    reference_year: int
    margin: float
    latest_values: List[Dict[str, Any]] = Field(default_factory=list)  # [{value, source_url, trust_level}]
    conflicted: bool = False
    decision_changing: bool = False
    volatile: bool = False
    volatility_min: Optional[float] = None
    volatility_max: Optional[float] = None
    years_used: List[int] = Field(default_factory=list)
```

Trong `CandidateProgram`, thêm sau dòng `data_uncertain_fields`:

```python
    cutoff_history: List[CutoffEntry] = Field(default_factory=list)
```

Trong `RankedRecommendation`, thêm sau dòng `cautions`:

```python
    cutoff_assessment: Optional[CutoffAssessment] = None
```

- [x] **Step 4: Sửa `ingestion/models/pipeline_models.py`** — thêm cuối file:

```python
class ExtractedCutoffFact(BaseModel):
    """Một dòng điểm chuẩn thô trích từ trang/PDF công bố (chưa normalize)."""
    school_name: str
    cutoff_year: int
    program_name: Optional[str] = None
    program_code: Optional[str] = None
    admission_method_raw: Optional[str] = None
    subject_combinations_raw: Optional[List[str]] = None
    cutoff_score_raw: str
    note_raw: Optional[str] = None
    source_reference: SourceReference
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0)
    extraction_method: str = "unknown"


class NormalizedCutoffRecord(BaseModel):
    """Bản ghi điểm chuẩn chuẩn hoá — lưu vào cutoff_records.

    admission_method là MÃ canonical (vd 'thpt_score'), KHÁC convention
    display-name của canonical_admission_records."""
    school_id: str
    program_id: Optional[str] = None
    program_name_canonical: Optional[str] = None
    program_name_raw: Optional[str] = None
    cutoff_year: int
    admission_method: str
    score_scale: Optional[float] = 30.0
    cutoff_score: float
    subject_combinations: List[str] = Field(default_factory=list)
    note: Optional[str] = None
    source_url: str
    source_trust_level: int = 3
    confidence_score: float = 0.9
    ingested_at: datetime = Field(default_factory=datetime.now)
```

- [x] **Step 5: Chạy test**

Run: `python -m pytest tests/agents/test_cutoff_models.py tests/test_state.py tests/ingestion/test_pydantic_config_migration.py -q`
Expected: PASS toàn bộ.

- [x] **Step 6: Commit**

```bash
git add agents/models.py ingestion/models/pipeline_models.py tests/agents/test_cutoff_models.py
git commit -m "feat: cutoff entry/assessment models and cutoff_history on candidates"
```

---

### Task 3: `save_cutoff_records` trong db_writer

**Files:**
- Modify: `ingestion/storage/db_writer.py` (thêm import + hàm mới cuối file)
- Test: `tests/ingestion/test_db_writer.py` (append)

- [x] **Step 1: Viết test fail** — append vào `tests/ingestion/test_db_writer.py` (file đã có `_TrackingCursor` + pattern monkeypatch `db_writer.get_cursor`; tái dùng đúng class đó):

```python
from ingestion.models.pipeline_models import NormalizedCutoffRecord


def _make_cutoff(source_url: str) -> NormalizedCutoffRecord:
    return NormalizedCutoffRecord(
        school_id="hust", program_id="computer_science",
        program_name_canonical="Khoa học Máy tính", program_name_raw="Khoa học máy tính (IT1)",
        cutoff_year=2025, admission_method="thpt_score", score_scale=30.0,
        cutoff_score=28.25, subject_combinations=["A00", "A01"],
        note="TTNV <= 2", source_url=source_url, source_trust_level=5,
    )


def test_save_cutoff_records_upserts_per_source(monkeypatch):
    cursor = _TrackingCursor()

    @contextmanager
    def fake_get_cursor(commit=True):
        yield cursor

    monkeypatch.setattr(db_writer, "get_cursor", fake_get_cursor)

    count = db_writer.save_cutoff_records([_make_cutoff("https://ts.hust.edu.vn/diem-chuan-2025")])

    assert count == 1
    sql, params = cursor.executions[0]
    assert "INSERT INTO cutoff_records" in sql
    assert "ON CONFLICT (school_id, cutoff_year, program_id, admission_method, source_url)" in sql
    assert "https://ts.hust.edu.vn/diem-chuan-2025" in params
    assert 28.25 in params


def test_save_cutoff_records_swallows_db_error_returns_zero(monkeypatch):
    @contextmanager
    def broken_get_cursor(commit=True):
        raise RuntimeError("db down")
        yield  # pragma: no cover

    monkeypatch.setattr(db_writer, "get_cursor", broken_get_cursor)

    assert db_writer.save_cutoff_records([_make_cutoff("https://x")]) == 0
```

- [x] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/ingestion/test_db_writer.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'save_cutoff_records'`

- [x] **Step 3: Implement** — trong `ingestion/storage/db_writer.py`: thêm `NormalizedCutoffRecord` vào import từ `pipeline_models`, thêm hàm cuối file:

```python
def save_cutoff_records(records: List[NormalizedCutoffRecord]) -> int:
    """Upsert điểm chuẩn lịch sử vào cutoff_records (per-source, mirror migration 016).

    Trả số record đã ghi; lỗi DB → log + trả 0 (caller CLI so count để exit code).
    """
    count = 0
    try:
        with get_cursor() as cur:
            for record in records:
                combos_json = (
                    json.dumps(record.subject_combinations, ensure_ascii=False)
                    if record.subject_combinations else None
                )
                cur.execute("""
                    INSERT INTO cutoff_records
                        (school_id, program_id, program_name_canonical, program_name_raw,
                         cutoff_year, admission_method, score_scale, cutoff_score,
                         subject_combinations, note, source_url,
                         source_trust_level, confidence_score)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (school_id, cutoff_year, program_id, admission_method, source_url)
                    DO UPDATE SET
                        program_name_canonical = EXCLUDED.program_name_canonical,
                        program_name_raw = EXCLUDED.program_name_raw,
                        score_scale = EXCLUDED.score_scale,
                        cutoff_score = EXCLUDED.cutoff_score,
                        subject_combinations = EXCLUDED.subject_combinations,
                        note = EXCLUDED.note,
                        source_trust_level = EXCLUDED.source_trust_level,
                        confidence_score = EXCLUDED.confidence_score,
                        ingested_at = NOW()
                """, (
                    record.school_id,
                    record.program_id,
                    record.program_name_canonical,
                    record.program_name_raw,
                    record.cutoff_year,
                    record.admission_method,
                    record.score_scale,
                    record.cutoff_score,
                    combos_json,
                    record.note,
                    record.source_url,
                    record.source_trust_level,
                    record.confidence_score,
                ))
                count += 1
        logger.info(f"Saved {count} cutoff records (upsert)")
    except Exception as e:
        logger.error(f"Failed to save cutoff records: {e}")
        return 0
    return count
```

- [x] **Step 4: Chạy test**

Run: `python -m pytest tests/ingestion/test_db_writer.py -q`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add ingestion/storage/db_writer.py tests/ingestion/test_db_writer.py
git commit -m "feat: save_cutoff_records upsert writer"
```

---

### Task 4: CLI `python -m ingestion.ingest_cutoffs` (đường seed)

**Files:**
- Create: `ingestion/ingest_cutoffs.py`
- Create: `ingestion/cutoff/__init__.py` (rỗng), `ingestion/cutoff/seeds/` (Task 5 đặt seed vào đây)
- Test: `tests/ingestion/test_cutoff_seed_loader.py`

- [x] **Step 1: Viết test fail** — create `tests/ingestion/test_cutoff_seed_loader.py`:

```python
import json

import ingestion.ingest_cutoffs as ingest_cutoffs


def _entry(**overrides):
    base = dict(
        school_id="hust", program_name_raw="Khoa học máy tính", program_code_raw="IT1",
        cutoff_year=2025, admission_method="thpt_score", score_scale=30,
        cutoff_score=28.25, subject_combinations=["A00", "A01"],
        note=None, source_url="https://ts.hust.edu.vn/diem-chuan-2025",
        source_trust_level=5,
    )
    base.update(overrides)
    return base


def _fake_map_program(name, code=None, school_id=""):
    if name and "máy tính" in name.lower():
        return ("computer_science", "Khoa học Máy tính")
    return (None, name)


def test_validate_entries_happy_path(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    records, errors = ingest_cutoffs.validate_entries([_entry()])
    assert errors == []
    assert len(records) == 1
    assert records[0].program_id == "computer_science"
    assert records[0].admission_method == "thpt_score"
    assert records[0].cutoff_score == 28.25


def test_validate_entries_is_atomic_and_reports_all_errors(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    bad = [
        _entry(cutoff_score=35.0),                      # vượt thang 30
        _entry(admission_method="khong_ton_tai"),       # method lạ
        _entry(program_name_raw="Ngành Không Tồn Tại"), # không resolve được
        _entry(source_url="  "),                        # thiếu nguồn
        _entry(cutoff_year=1999),                       # năm ngoài range
    ]
    records, errors = ingest_cutoffs.validate_entries(bad)
    assert records == []      # entry hợp lệ duy nhất cũng không có ở đây — list toàn lỗi
    assert len(errors) == 5   # MỌI lỗi đều được liệt kê, không dừng ở lỗi đầu


def test_school_filter(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    records, errors = ingest_cutoffs.validate_entries(
        [_entry(), _entry(school_id="vnu_uet")], school_filter="hust",
    )
    assert errors == []
    assert len(records) == 1 and records[0].school_id == "hust"


def test_main_exits_nonzero_and_writes_nothing_on_any_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    saved = []
    monkeypatch.setattr(ingest_cutoffs, "save_cutoff_records", lambda rs: saved.append(rs) or len(rs))
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([_entry(), _entry(cutoff_score=99)]), encoding="utf-8")

    code = ingest_cutoffs._main(["--seed", str(seed)])

    assert code == 1
    assert saved == []                      # atomic: 1 entry lỗi → KHÔNG ghi gì
    assert "99" in capsys.readouterr().out  # lỗi được in ra


def test_main_dry_run_does_not_write(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    saved = []
    monkeypatch.setattr(ingest_cutoffs, "save_cutoff_records", lambda rs: saved.append(rs) or len(rs))
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([_entry()]), encoding="utf-8")

    assert ingest_cutoffs._main(["--seed", str(seed), "--dry-run"]) == 0
    assert saved == []


def test_main_writes_and_verifies_count(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    monkeypatch.setattr(ingest_cutoffs, "save_cutoff_records", lambda rs: len(rs))
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([_entry()]), encoding="utf-8")

    assert ingest_cutoffs._main(["--seed", str(seed)]) == 0


def test_main_exit_2_when_db_write_short(monkeypatch, tmp_path):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    monkeypatch.setattr(ingest_cutoffs, "save_cutoff_records", lambda rs: 0)  # DB lỗi → 0
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([_entry()]), encoding="utf-8")

    assert ingest_cutoffs._main(["--seed", str(seed)]) == 2
```

- [x] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/ingestion/test_cutoff_seed_loader.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.ingest_cutoffs'`

- [x] **Step 3: Implement** — create `ingestion/cutoff/__init__.py` (file rỗng) và `ingestion/ingest_cutoffs.py`:

```python
"""CLI: nạp điểm chuẩn lịch sử curated vào cutoff_records (Giai đoạn 2).

    python -m ingestion.ingest_cutoffs --seed                 # seed mặc định
    python -m ingestion.ingest_cutoffs --seed path.json --dry-run
    python -m ingestion.ingest_cutoffs --seed --school hust

Seed phải sạch 100%: BẤT KỲ entry lỗi nào → in toàn bộ lỗi, exit 1, KHÔNG ghi gì
(lỗi resolve ngành nghĩa là cần bổ sung alias programs.json hoặc sửa seed —
không được âm thầm bỏ qua). Exit 2 = validate OK nhưng DB ghi thiếu.
"""
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from ingestion.config.settings import ADMISSION_YEAR
from ingestion.models.pipeline_models import NormalizedCutoffRecord
from ingestion.normalization.program_mapper import map_program
from ingestion.storage.db_writer import save_cutoff_records
from services.profile.admission_methods import METHOD_CODES

logger = logging.getLogger(__name__)

DEFAULT_SEED = Path(__file__).parent / "cutoff" / "seeds" / "cutoff_2023_2025.json"
MIN_CUTOFF_YEAR = 2020


def load_seed(path: Path) -> list:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_entries(
    entries: list, school_filter: Optional[str] = None,
) -> Tuple[List[NormalizedCutoffRecord], List[str]]:
    """Validate TOÀN BỘ entries; trả (records, errors). errors khác rỗng ⇒ không dùng records."""
    records: List[NormalizedCutoffRecord] = []
    errors: List[str] = []
    for i, e in enumerate(entries):
        school_id = (e.get("school_id") or "").strip()
        if school_filter and school_id != school_filter:
            continue
        label = f"entry[{i}] {school_id or '?'}/{e.get('program_name_raw')}/{e.get('cutoff_year')}"

        if not school_id:
            errors.append(f"{label}: thiếu school_id")
            continue
        method = e.get("admission_method")
        if method not in METHOD_CODES:
            errors.append(f"{label}: admission_method {method!r} không thuộc METHOD_CODES")
            continue
        try:
            score = float(e.get("cutoff_score"))
            scale = float(e.get("score_scale") or 30)
        except (TypeError, ValueError):
            errors.append(f"{label}: cutoff_score/score_scale không phải số ({e.get('cutoff_score')!r})")
            continue
        if not (0 < score <= scale):
            errors.append(f"{label}: cutoff_score {score} ngoài khoảng (0, {scale}]")
            continue
        year = e.get("cutoff_year")
        if not isinstance(year, int) or not (MIN_CUTOFF_YEAR <= year <= ADMISSION_YEAR):
            errors.append(f"{label}: cutoff_year {year!r} ngoài [{MIN_CUTOFF_YEAR}, {ADMISSION_YEAR}]")
            continue
        source_url = (e.get("source_url") or "").strip()
        if not source_url:
            errors.append(f"{label}: thiếu source_url (mỗi con số phải kèm nguồn thật)")
            continue
        program_id, canonical = map_program(
            e.get("program_name_raw"), e.get("program_code_raw"), school_id=school_id,
        )
        if not program_id or program_id == e.get("program_code_raw"):
            errors.append(
                f"{label}: không resolve được ngành {e.get('program_name_raw')!r} "
                "— bổ sung alias vào ingestion/normalization/dictionaries/programs.json"
            )
            continue

        records.append(
            NormalizedCutoffRecord(
                school_id=school_id,
                program_id=program_id,
                program_name_canonical=canonical,
                program_name_raw=e.get("program_name_raw"),
                cutoff_year=year,
                admission_method=method,
                score_scale=scale,
                cutoff_score=score,
                subject_combinations=list(e.get("subject_combinations") or []),
                note=e.get("note"),
                source_url=source_url,
                source_trust_level=int(e.get("source_trust_level") or 3),
            )
        )
    if errors:
        return [], errors
    return records, []


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Nạp điểm chuẩn lịch sử curated vào cutoff_records")
    parser.add_argument("--seed", nargs="?", const=str(DEFAULT_SEED), default=None,
                        help="đường dẫn seed JSON (mặc định: seed commit sẵn)")
    parser.add_argument("--school", default=None, help="chỉ nạp một trường (hust|vnu_uet)")
    parser.add_argument("--dry-run", action="store_true", help="chỉ validate + in, không ghi DB")
    args = parser.parse_args(argv)

    if not args.seed:
        parser.error("cần --seed (đường parser --source-url bổ sung ở plan 5)")

    entries = load_seed(Path(args.seed))
    records, errors = validate_entries(entries, school_filter=args.school)
    if errors:
        print(f"Seed KHÔNG hợp lệ — {len(errors)} lỗi, không ghi gì:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"Validate OK: {len(records)} bản ghi điểm chuẩn.")
    if args.dry_run:
        for r in records:
            print(f"  {r.school_id} {r.cutoff_year} {r.program_id} "
                  f"{r.admission_method} = {r.cutoff_score} ({r.source_url})")
        return 0

    saved = save_cutoff_records(records)
    if saved != len(records):
        print(f"LỖI: chỉ ghi được {saved}/{len(records)} bản ghi — kiểm tra DB/migration 016.")
        return 2
    print(f"Đã upsert {saved} bản ghi vào cutoff_records.")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(_main())
```

- [x] **Step 4: Chạy test**

Run: `python -m pytest tests/ingestion/test_cutoff_seed_loader.py -q`
Expected: PASS 7 test.

- [x] **Step 5: Commit**

```bash
git add ingestion/ingest_cutoffs.py ingestion/cutoff/__init__.py tests/ingestion/test_cutoff_seed_loader.py
git commit -m "feat: ingest_cutoffs CLI with atomic seed validation"
```

---

### Task 5: Seed curated điểm chuẩn 2023–2025 (THỦ CÔNG — số liệu thật, nguồn thật)

**Files:**
- Create: `ingestion/cutoff/seeds/cutoff_2023_2025.json`

> Task này là CURATION DỮ LIỆU THẬT, không phải code. Tuyệt đối KHÔNG bịa số.
> Mỗi con số phải chép từ trang chính thức và dán đúng URL trang đó vào `source_url`.

- [x] **Step 1: Tra số liệu** — dùng WebFetch/WebSearch hoặc trình duyệt:
  - HUST: trang công bố điểm chuẩn các năm trên `ts.hust.edu.vn` (tìm "điểm chuẩn 2025 site:ts.hust.edu.vn", tương tự 2024/2023). Phương thức "Xét điểm thi TN THPT" (thang 30).
  - VNU-UET: `tuyensinh.uet.vnu.edu.vn` (thông báo điểm trúng tuyển từng năm).
  - Nguồn THỨ HAI cho EC-16: cổng ĐHQGHN (`tuyensinh.vnu.edu.vn`) công bố điểm chuẩn các trường thành viên — dùng cho các chương trình VNU-UET; với HUST có thể dùng đề án/thông báo PDF đính kèm nếu có. **Nếu không tìm được nguồn chính thức thứ hai cho một (chương trình, năm), KHÔNG bịa cặp conflict — EC-16 vẫn được test bằng fixture (Plan 3/4), và ghi chú vào cuối seed file bằng key `"_notes"`.**
- [x] **Step 2: Soạn seed** — phủ tối thiểu: 2 trường × 3 năm (2023/2024/2025) × ≥4 chương trình/trường thuộc nhóm CNTT (ưu tiên: computer_science, data_science, information_technology, artificial_intelligence — khớp kịch bản demo); thêm entry nguồn-thứ-hai cho ≥2 (chương trình, năm 2025) nếu Step 1 tìm được. Format mỗi entry (đúng schema validate ở Task 4):

```json
[
  {
    "school_id": "hust",
    "program_name_raw": "<tên ngành đúng như trang công bố>",
    "program_code_raw": "<mã ngành nếu có, vd IT1>",
    "cutoff_year": 2025,
    "admission_method": "thpt_score",
    "score_scale": 30,
    "cutoff_score": 0.0,
    "subject_combinations": ["A00", "A01"],
    "note": "<tiêu chí phụ nếu trang ghi, vd TTNV <= 2; null nếu không>",
    "source_url": "<URL trang công bố — BẮT BUỘC thật>",
    "source_trust_level": 5
  }
]
```

  (Giá trị `cutoff_score: 0.0` ở trên là minh hoạ schema — file thật phải là số chép từ nguồn; loader sẽ từ chối 0.0 vì ngoài khoảng (0, 30].)
- [x] **Step 3: Validate dry-run**

Run: `python -m ingestion.ingest_cutoffs --seed --dry-run`
Expected: `Validate OK: N bản ghi` và bảng liệt kê. Nếu lỗi resolve ngành → bổ sung alias vào `ingestion/normalization/dictionaries/programs.json` (commit kèm) rồi chạy lại.

- [x] **Step 4: Nạp thật (cần Docker DB + migration 016)**

Run: `docker compose up -d --wait db && python -m db.setup_db && python -m ingestion.ingest_cutoffs --seed`
Expected: `Đã upsert N bản ghi`. Chạy lại lần 2 → vẫn N (idempotent).

- [x] **Step 5: Commit**

```bash
git add ingestion/cutoff/seeds/cutoff_2023_2025.json ingestion/normalization/dictionaries/programs.json
git commit -m "feat: curated historical cutoff seed 2023-2025 (HUST, VNU-UET)"
```
