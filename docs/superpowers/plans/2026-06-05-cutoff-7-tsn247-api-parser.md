# Cutoff Plan 7 — Parser API tuyensinh247 + backfill 2022–2024 + re-run HTML 2025

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parser `tuyensinh247_cutoff_api` (JSON) chạy qua runner `--source-url` sẵn có, backfill điểm chuẩn BKA 2022–2024 và re-run HTML 2025 với dictionary mới → cutoff_records đủ 4 năm × các phương thức (trust 3) cạnh seed trust 5.

**Architecture:** API nội bộ trang (nút "Xem thêm" gọi): `GET https://diemthi.tuyensinh247.com/api/common/cutoff-score?school_id=302&method_id={m}&year={y}` trả `{"success":true,"data":[{code,name,block,mark,year,admission_name,...}]}`. Parser cùng chữ ký parser HTML, đăng ký thêm vào `CUTOFF_PARSERS` — runner KHÔNG sửa. `normalize_cutoff_facts` tự hưởng stage-code (plan 6) vì đã truyền `f.program_code`. Backfill API chỉ 2022–2024: **2025 đi đường HTML** (re-run sau dictionary mới) để 1 nguồn aggregator không sinh 2 row trùng giá trị khác source_url. Spec: `docs/superpowers/specs/2026-06-05-cutoff-tsn247-api-dictionary-design.md`.

**Tech Stack:** json (stdlib), pytest, fixture JSON tĩnh.

**Phụ thuộc:** Plan 6 (codes + dictionary). DB Docker cho bước chạy thật.

**Bake sẵn từ probe 2026-06-05:**
- Coverage API: 2022 (m1=55, m6=60), 2023 (63/61), 2024 (64/64 + m10=64), 2025 đủ 4 method.
  method_id: 1=THPT, 6=ĐGTD, 10=Xét tuyển kết hợp, 12=Chứng chỉ quốc tế.
- Quirk 2022: mã có hậu tố `y`/`Y` (`IT2y`, `TROY-ITy`) — strip 1 ký tự cuối ở PARSER.
- Tên trong API có thể chứa **newline nhúng** ("…tái tạo\n(CT tiên tiến)") → normalize `\s+`→" ".
- `admission_name` map sạch qua `map_method(..., school_id="hust")` (đã verify ở plan 5).
- `mark` là số (float/int) → `str(mark)` khớp `_SCORE_RE` của normalize ("21.0", "50.08", "55").
- EM1 2022 tên cũ "Kinh tế công nghiệp" — code map về `energy_management` (ngành đổi tên, chấp nhận).

---

### Task 1: Fixture snapshot API

**Files:**
- Modify: `scripts/_probe_tsn247_cutoff.py` (thêm chế độ API)
- Create: `tests/fixtures/tsn247_bka_api_thpt_2024.json`
- Create: `tests/fixtures/tsn247_bka_api_dgtd_2022.json` (case hậu tố "y")

- [ ] **Step 1: Thêm chế độ API vào probe script** — sửa `scripts/_probe_tsn247_cutoff.py`:
(a) đổi tên hàm `main()` hiện có thành `probe_html()` (KHÔNG sửa thân hàm);
(b) thêm 2 hàm mới trước `if __name__`:

```python
API_URL = ("https://diemthi.tuyensinh247.com/api/common/cutoff-score"
           "?school_id={school}&method_id={method}&year={year}")


def probe_api(school: str, method: str, year: str, save: str | None) -> None:
    url = API_URL.format(school=school, method=method, year=year)
    r = http_fetch(url)
    import json as _json
    payload = _json.loads(r.raw_content)
    rows = payload.get("data") or []
    print(f"status={r.http_status} success={payload.get('success')} rows={len(rows)}")
    for row in rows[:5]:
        print(f"  {row.get('code')!r} | {(row.get('name') or '')[:45]!r} | "
              f"{row.get('block')!r} | {row.get('mark')}")
    if save:
        Path(save).write_bytes(r.raw_content)
        print(f"Đã lưu {len(r.raw_content)} bytes vào {save}")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "api":
        # python -m scripts._probe_tsn247_cutoff api <school_id> <method_id> <year> [out.json]
        probe_api(sys.argv[2], sys.argv[3], sys.argv[4],
                  sys.argv[5] if len(sys.argv) > 5 else None)
        return
    probe_html()
```

(`if __name__ == "__main__": main()` cuối file giữ nguyên.)

- [ ] **Step 2: Snapshot 2 fixture**

```bash
python -m scripts._probe_tsn247_cutoff api 302 1 2024 tests/fixtures/tsn247_bka_api_thpt_2024.json
python -m scripts._probe_tsn247_cutoff api 302 6 2022 tests/fixtures/tsn247_bka_api_dgtd_2022.json
```

Expected: 2024 rows=64 (mã sạch `IT1`); 2022 rows=60 (mã hậu tố `y`: `IT1y`/`IT2y`).
Nếu cấu trúc đổi (success≠true / thiếu field) → DỪNG, báo lại.

---

### Task 2: Parser `tuyensinh247_cutoff_api`

**Files:**
- Create: `ingestion/parsers/tuyensinh247_cutoff_api_parser.py`
- Test: `tests/ingestion/test_tuyensinh247_cutoff_api_parser.py`

- [ ] **Step 1: Viết test fail** — create `tests/ingestion/test_tuyensinh247_cutoff_api_parser.py`:

```python
import json
from pathlib import Path

from ingestion.parsers.tuyensinh247_cutoff_api_parser import Tuyensinh247CutoffApiParser

_URL = ("https://diemthi.tuyensinh247.com/api/common/cutoff-score"
        "?school_id=302&method_id=1&year=2024")

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _payload(rows, success=True):
    return json.dumps({"success": success, "data": rows}, ensure_ascii=False).encode("utf-8")


_ROWS = [
    {"code": "IT1", "name": "CNTT: Khoa học Máy tính", "block": "A00;A01",
     "mark": 28.53, "year": 2024, "admission_name": "Điểm thi THPT"},
    # quirk 2022: hậu tố y + newline nhúng trong tên + block rỗng
    {"code": "EE-E18y", "name": "Hệ thống điện và năng lượng tái tạo\n(CT tiên tiến)",
     "block": "", "mark": 55, "year": 2022, "admission_name": "Điểm xét tuyển kết hợp"},
    {"code": "XX1", "name": "Thiếu điểm", "block": "A00",
     "mark": None, "year": 2024, "admission_name": "Điểm thi THPT"},      # bỏ qua
    {"code": "XX2", "name": "", "block": "A00",
     "mark": 25.0, "year": 2024, "admission_name": "Điểm thi THPT"},      # bỏ qua
]


def test_parses_rows_with_code_block_and_year_from_row():
    facts = Tuyensinh247CutoffApiParser().parse(_payload(_ROWS), _URL)
    assert len(facts) == 2                       # 2 row hợp lệ, 2 row thiếu bị bỏ
    f = facts[0]
    assert f.program_code == "IT1"
    assert f.program_name == "CNTT: Khoa học Máy tính"
    assert f.subject_combinations_raw == ["A00", "A01"]
    assert f.cutoff_score_raw == "28.53"
    assert f.cutoff_year == 2024                 # đọc từ row, không tin URL
    assert f.admission_method_raw == "Điểm thi THPT"
    assert f.source_reference.trust_level == 3
    assert f.extraction_method == "tuyensinh247_cutoff_api"
    g = facts[1]
    assert g.program_code == "EE-E18"            # strip hậu tố y
    assert g.program_name == "Hệ thống điện và năng lượng tái tạo (CT tiên tiến)"  # \s+ → " "
    assert g.subject_combinations_raw is None    # block rỗng
    assert g.cutoff_score_raw == "55"
    assert g.cutoff_year == 2022


def test_year_filter():
    facts = Tuyensinh247CutoffApiParser().parse(_payload(_ROWS), _URL, cutoff_year=2022)
    assert [f.cutoff_year for f in facts] == [2022]


def test_success_false_or_bad_json_returns_empty():
    parser = Tuyensinh247CutoffApiParser()
    assert parser.parse(_payload([], success=False), _URL) == []
    assert parser.parse(b"<html>not json</html>", _URL) == []
    assert parser.parse(json.dumps({"success": True, "data": "oops"}).encode(), _URL) == []


def test_real_fixture_thpt_2024():
    content = (_FIXTURES / "tsn247_bka_api_thpt_2024.json").read_bytes()
    facts = Tuyensinh247CutoffApiParser().parse(content, _URL)
    assert len(facts) >= 60
    assert {f.cutoff_year for f in facts} == {2024}
    it1 = [f for f in facts if f.program_code == "IT1"]
    assert it1 and it1[0].cutoff_score_raw == "28.53"


def test_real_fixture_dgtd_2022_strips_y_suffix():
    content = (_FIXTURES / "tsn247_bka_api_dgtd_2022.json").read_bytes()
    facts = Tuyensinh247CutoffApiParser().parse(content, _URL)
    assert len(facts) >= 50
    assert {f.cutoff_year for f in facts} == {2022}
    assert all(not (f.program_code or "").lower().endswith("y")
               or len(f.program_code) <= 1 for f in facts)
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/ingestion/test_tuyensinh247_cutoff_api_parser.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement** — create `ingestion/parsers/tuyensinh247_cutoff_api_parser.py`:

```python
"""Tuyensinh247 cutoff API parser (JSON) — Giai đoạn 2, plan 7.

Endpoint nội bộ trang (nút "Xem thêm" gọi):
GET /api/common/cutoff-score?school_id={id}&method_id={m}&year={y}
→ {"success": true, "data": [{code, name, block, mark, year, admission_name, ...}]}

Ưu thế so với bảng HTML: có MÃ tuyển sinh (code) → map_program stage-code chính xác
tuyệt đối; có tổ hợp (block) cho mọi phương thức. API không phải public contract —
fixture snapshot + source active:false; đổi schema thì trả [] + warning, runner exit 1.

Aggregator (trust 3). Trả ExtractedCutoffFact → chạy qua runner
`ingestion.ingest_cutoffs --source-url`, KHÔNG qua IngestionPipeline.
"""
from __future__ import annotations

import json
import logging
import re
from typing import List, Optional

from ingestion.models.pipeline_models import ExtractedCutoffFact, SourceReference

logger = logging.getLogger(__name__)

_WS_RE = re.compile(r"\s+")


def _norm_ws(value) -> str:
    return _WS_RE.sub(" ", str(value)).strip() if value else ""


class Tuyensinh247CutoffApiParser:
    """Đăng ký qua CUTOFF_PARSERS trong ingest_cutoffs (như parser HTML plan 5)."""

    parser_profile = "tuyensinh247_cutoff_api"

    def parse(
        self,
        content: bytes,
        source_url: str,
        cutoff_year: Optional[int] = None,   # filter tùy chọn; năm thật đọc từ row
        school_id: str = "hust",
        school_name: str = "Đại học Bách khoa Hà Nội",
        trust_level: int = 3,
    ) -> List[ExtractedCutoffFact]:
        try:
            payload = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            logger.warning("Tuyensinh247CutoffApiParser: body không phải JSON từ %s", source_url)
            return []
        if not isinstance(payload, dict):
            logger.warning("Tuyensinh247CutoffApiParser: payload không phải object từ %s", source_url)
            return []
        rows = payload.get("data")
        if not payload.get("success") or not isinstance(rows, list):
            logger.warning(
                "Tuyensinh247CutoffApiParser: payload không hợp lệ (success=%r) từ %s",
                payload.get("success"), source_url,
            )
            return []

        facts: List[ExtractedCutoffFact] = []
        for row in rows:
            name = _norm_ws(row.get("name"))
            mark = row.get("mark")
            year = row.get("year")
            if not name or mark is None or not isinstance(year, int):
                logger.debug("API row thiếu name/mark/year, bỏ qua: %r", row.get("code"))
                continue
            if cutoff_year is not None and year != cutoff_year:
                continue
            code = _norm_ws(row.get("code"))
            # Quirk dữ liệu 2022 của tsn247: mã mang hậu tố 'y' (IT2y, TROY-ITy)
            if len(code) > 1 and code[-1] in "yY":
                code = code[:-1]
            block = _norm_ws(row.get("block"))
            combos = [s.strip() for s in block.split(";") if s.strip()] or None

            facts.append(
                ExtractedCutoffFact(
                    school_name=school_name,
                    cutoff_year=year,
                    program_name=name,
                    program_code=code or None,
                    admission_method_raw=_norm_ws(row.get("admission_name")) or None,
                    subject_combinations_raw=combos,
                    cutoff_score_raw=str(mark),
                    note_raw=_norm_ws(row.get("introtext")) or None,
                    source_reference=SourceReference(
                        source_id=f"tsn247_api_{school_id}_{year}",
                        source_url=source_url,
                        school_id=school_id,
                        trust_level=trust_level,
                    ),
                    confidence_score=0.85,
                    extraction_method="tuyensinh247_cutoff_api",
                )
            )

        logger.info(
            "Tuyensinh247CutoffApiParser: %d cutoff facts from %s", len(facts), source_url
        )
        return facts
```

- [ ] **Step 4: Chạy test**

Run: `python -m pytest tests/ingestion/test_tuyensinh247_cutoff_api_parser.py -q`
Expected: PASS (chỉnh ngưỡng `>= 60`/`>= 50` nếu snapshot thật lệch nhẹ — ghi số thật vào test).

- [ ] **Step 5: Commit**

```bash
git add ingestion/parsers/tuyensinh247_cutoff_api_parser.py \
        tests/ingestion/test_tuyensinh247_cutoff_api_parser.py \
        tests/fixtures/tsn247_bka_api_thpt_2024.json \
        tests/fixtures/tsn247_bka_api_dgtd_2022.json \
        scripts/_probe_tsn247_cutoff.py
git commit -m "feat: tuyensinh247 cutoff API parser (JSON, admission codes, 2022 y-suffix quirk)"
```

---

### Task 3: Đăng ký parser + bookkeeping + backfill thật

**Files:**
- Modify: `ingestion/ingest_cutoffs.py` (CUTOFF_PARSERS + import)
- Modify: `ingestion/registry/seeds/initial_sources.json` (entry API)
- Test: `tests/ingestion/test_cutoff_seed_loader.py` (append)

- [ ] **Step 1: Viết test fail** — append vào `tests/ingestion/test_cutoff_seed_loader.py`:

```python
def test_cutoff_parsers_registry_has_both_tsn247_parsers():
    assert set(ingest_cutoffs.CUTOFF_PARSERS) >= {
        "tuyensinh247_cutoff_html", "tuyensinh247_cutoff_api",
    }


def test_main_source_url_api_parser_choice(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)

    class _FakeFetch:
        raw_content = b'{"success": true, "data": []}'
        http_status = 200

    monkeypatch.setattr(ingest_cutoffs, "http_fetch", lambda url, **kw: _FakeFetch())
    monkeypatch.setattr(
        type(ingest_cutoffs.CUTOFF_PARSERS["tuyensinh247_cutoff_api"]), "parse",
        lambda self, content, source_url, cutoff_year=None, **kw: [_fact()],
    )
    saved = []
    monkeypatch.setattr(ingest_cutoffs, "save_cutoff_records", lambda rs: saved.append(rs) or len(rs))

    code = ingest_cutoffs._main([
        "--source-url", "https://diemthi.tuyensinh247.com/api/common/cutoff-score?school_id=302&method_id=1&year=2024",
        "--parser", "tuyensinh247_cutoff_api",
    ])
    assert code == 0
    assert len(saved[0]) == 1
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/ingestion/test_cutoff_seed_loader.py -q`
Expected: FAIL — `KeyError: 'tuyensinh247_cutoff_api'`.

- [ ] **Step 3: Implement** — sửa `ingestion/ingest_cutoffs.py`:

(a) thêm import (cạnh import parser HTML):

```python
from ingestion.parsers.tuyensinh247_cutoff_api_parser import Tuyensinh247CutoffApiParser
```

(b) mở rộng registry:

```python
CUTOFF_PARSERS = {
    Tuyensinh247CutoffParser.parser_profile: Tuyensinh247CutoffParser(),
    Tuyensinh247CutoffApiParser.parser_profile: Tuyensinh247CutoffApiParser(),
}
```

(c) `ingestion/registry/seeds/initial_sources.json` — append entry sau `hust_cutoff_tsn247_2025`:

```json
{
  "source_id": "hust_cutoff_tsn247_api",
  "school_id": "hust",
  "school_name": "Đại học Bách khoa Hà Nội",
  "source_type": "cutoff_announcement",
  "root_url": "https://diemthi.tuyensinh247.com/api/common/cutoff-score?school_id=302",
  "trust_level": 3,
  "priority": 5,
  "fetch_strategy": "http",
  "parser_profile": "tuyensinh247_cutoff_api",
  "update_frequency_hint": "yearly",
  "is_official": false,
  "active": false
}
```

(`active: false` cùng lý do plan 5: trả ExtractedCutoffFact, không cho IngestionPipeline nhặt.)

- [ ] **Step 4: Chạy test**

Run: `python -m pytest tests/ingestion/ -q`
Expected: PASS.

- [ ] **Step 5: Backfill thật (DB up: `docker start advisory-db`)** — 7 lệnh 2022–2024:

```bash
set -a; source .env; set +a
BASE="https://diemthi.tuyensinh247.com/api/common/cutoff-score?school_id=302"
for ym in "2022 1" "2022 6" "2023 1" "2023 6" "2024 1" "2024 6" "2024 10"; do
  set -- $ym
  python -m ingestion.ingest_cutoffs \
    --source-url "${BASE}&method_id=$2&year=$1" \
    --parser tuyensinh247_cutoff_api
done
```

Expected: mỗi lệnh "Đã upsert N/N bản ghi" — N ≈ 55–64; SKIP chỉ còn mã/tên không thuộc 65 mã
hiện hành (mã cổ 2022 đã đổi số — fallback tên không trúng); in từng dòng SKIP để soát.

- [ ] **Step 6: Re-run HTML 2025 với dictionary mới** (row SKIP cũ giờ resolve):

```bash
python -m ingestion.ingest_cutoffs \
  --source-url https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html
```

Expected: upsert ~250+ bản ghi (trước: 120) — cùng source_url nên đè/bổ sung, không nhân đôi.

- [ ] **Step 7: Verify DB**

```bash
docker exec advisory-db psql -U postgres -d admission -c "
SELECT cutoff_year, admission_method, count(*) FROM cutoff_records
WHERE school_id='hust' AND source_url LIKE '%tuyensinh247%'
GROUP BY 1,2 ORDER BY 1,2;"
docker exec advisory-db psql -U postgres -d admission -c "
SELECT cutoff_year, cutoff_score FROM cutoff_records
WHERE program_id='computer_science_troy' ORDER BY 1;"
```

Expected: đủ nhóm (2022×2, 2023×2, 2024×3, 2025×4); `computer_science_troy` có row riêng
(2022: 25.15 THPT...), KHÔNG đè `computer_science`.

- [ ] **Step 8: Commit**

```bash
git add ingestion/ingest_cutoffs.py ingestion/registry/seeds/initial_sources.json \
        tests/ingestion/test_cutoff_seed_loader.py
git commit -m "feat: register tsn247 API cutoff parser and backfill 2022-2024 + full 2025"
```

---

### Task 4: Khép plan

- [ ] **Step 1:** `python -m pytest -q` → toàn xanh; DB up: `python -m pytest tests/integration tests/e2e -q` → xanh.
- [ ] **Step 2:** Tick checkbox plan này + cập nhật index plan + commit docs.
