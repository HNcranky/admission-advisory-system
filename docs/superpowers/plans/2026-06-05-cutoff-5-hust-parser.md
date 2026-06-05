# Cutoff Plan 5 — Parser điểm chuẩn tuyensinh247 (proof-of-automation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Cập nhật 2026-06-05:** đổi target từ trang chính thức `ts.hust.edu.vn` sang aggregator
> `diemthi.tuyensinh247.com` (đã duyệt với user, xem spec quyết định #1). Trang đã probe:
> HTML tĩnh, không chặn UA, 4 bảng phương thức đồng nhất — không còn bước "tìm URL".

**Goal:** Một parser deterministic `tuyensinh247_cutoff_html` parse trang điểm chuẩn BKA
`https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html` thành
`ExtractedCutoffFact` (đủ 4 bảng phương thức), chạy qua runner `ingest_cutoffs --source-url`
(fetch → parse → normalize → save), chứng minh đường tự động hoá bên cạnh seed.

**Architecture:** Parser generic theo template tuyensinh247 — mỗi phương thức một bảng
`Tên ngành | Tổ hợp môn | Điểm chuẩn | Ghi chú` đứng sau heading `h3`
"Điểm chuẩn theo phương thức {X} năm {Y}"; method + năm đọc từ heading (không hardcode), school
truyền qua tham số → thêm trường sau này chỉ thêm entry source. Runner nhận URL + tham số tường minh
(`--source-url --parser --school --year --trust`) thay vì đi qua `IngestionPipeline` — pipeline chính
expect `ExtractedAdmissionFact`, trộn fact type sẽ vỡ normalizer. Source vẫn được đăng ký vào registry
để bookkeeping nhưng `active: false` để `run_for_school`/`run_all_schools` không nhặt nhầm.

**Tech Stack:** BeautifulSoup, pytest fixture HTML tĩnh.

**Phụ thuộc:** Plan 1 (models, `save_cutoff_records`, CLI khung).

**Đã probe trước (2026-06-05) — bake vào plan:**
- HTML tĩnh (curl thường ra đủ bảng), không chặn UA, HTTP 200 cả khi không gửi UA.
- 4 heading `h3` (chữ nằm trong element con — dùng `get_text(" ", strip=True)` để có khoảng trắng):
  "Điểm chuẩn theo phương thức **Điểm thi THPT** năm **2025**" (thang 30, có cột tổ hợp),
  "… **Điểm Đánh giá Tư duy** …" (thang 100), "… **Điểm xét tuyển kết hợp** …",
  "… **Chứng chỉ quốc tế** …".
- 4 text phương thức map sạch qua `map_method(raw, school_id="hust")` sẵn có →
  `thpt_score` / `competency_test` / `combined` / `talent_admission` (đã verify, KHÔNG cần thêm alias).
- Mỗi bảng có row rác thứ 2: "Tra cứu tại: Tuyensinh247.com - Học trực tuyến…" (1 cell) → loại
  bằng điều kiện cột điểm là số. KHÔNG có cột mã ngành (IT1…) → `program_code=None`, resolve
  bằng `map_program` fuzzy theo tên.
- Dữ liệu năm cũ (nút "Xem thêm … năm 2024") load qua JS — NGOÀI phạm vi; 2023–2024 đi đường seed.

---

### Task 1: Snapshot fixture trang thật

**Files:**
- Create: `tests/fixtures/tsn247_bka_cutoff_2025.html`

- [ ] **Step 1: Fetch + verify cấu trúc** — viết nhanh `scripts/_probe_tsn247_cutoff.py` theo pattern
  `scripts/hust_preflight_inspect.py`: fetch
  `https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html`
  (lưu ý `ADVISORY_FETCH_VERIFY_SSL` mặc định off), in: số `h3` khớp regex
  `điểm chuẩn theo phương thức\s*(.+?)\s*năm\s*(20\d{2})` (case-insensitive, trên
  `get_text(" ", strip=True)`), số bảng, header + 3 row đầu mỗi bảng. Expected: 4 heading 2025,
  4 bảng header `Tên ngành | Tổ hợp môn | Điểm chuẩn | Ghi chú`. Nếu cấu trúc đã đổi → dừng, báo lại.
- [ ] **Step 2: Snapshot fixture** — lưu HTML trang thật vào
  `tests/fixtures/tsn247_bka_cutoff_2025.html`. Có thể cắt `<script>`/`<style>`/phần ngoài nội dung
  cho nhẹ file, GIỮ NGUYÊN 4 heading `h3` + 4 bảng (~100KB nguyên trang là chấp nhận được).

---

### Task 2: Parser `tuyensinh247_cutoff_html`

**Files:**
- Create: `ingestion/parsers/tuyensinh247_cutoff_parser.py`
- Test: `tests/ingestion/test_tuyensinh247_cutoff_parser.py`

(KHÔNG sửa `base_parser.py` — parser này cố ý nằm ngoài `ParserRegistry` của pipeline
chính vì trả `ExtractedCutoffFact`; đăng ký qua `CUTOFF_PARSERS` trong `ingest_cutoffs` ở Task 3.)

- [ ] **Step 1: Viết test fail** — create `tests/ingestion/test_tuyensinh247_cutoff_parser.py`.
  Test 1–3 dùng fixture synthetic (deterministic, commit kèm test); test 4 dùng fixture thật từ Task 1:

```python
from pathlib import Path

from ingestion.parsers.tuyensinh247_cutoff_parser import Tuyensinh247CutoffParser

_URL = "https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html"

_SYNTHETIC = """
<html><body>
<h3>Điểm chuẩn theo phương thức <b>Điểm thi THPT</b> năm <b>2025</b></h3>
<table>
  <tr><th>Tên ngành</th><th>Tổ hợp môn</th><th>Điểm chuẩn</th><th>Ghi chú</th></tr>
  <tr><td colspan="4">Tra cứu tại: Tuyensinh247.com - Học trực tuyến</td></tr>
  <tr><td>Khoa học máy tính</td><td>A00; A01</td><td>28,25</td><td>Môn chính: Toán</td></tr>
  <tr><td>Kỹ thuật máy tính</td><td>A00; A01</td><td>27.5</td><td></td></tr>
</table>
<h3>Điểm chuẩn theo phương thức Điểm Đánh giá Tư duy năm 2025</h3>
<table>
  <tr><th>Tên ngành</th><th>Tổ hợp môn</th><th>Điểm chuẩn</th><th>Ghi chú</th></tr>
  <tr><td>Khoa học máy tính</td><td></td><td>83.9</td><td></td></tr>
</table>
<h3>Bài viết liên quan</h3>
<table><tr><th>Tiêu đề</th></tr><tr><td>Tin tức 1000</td></tr></table>
</body></html>
"""


def test_parses_synthetic_sections():
    facts = Tuyensinh247CutoffParser().parse(_SYNTHETIC.encode("utf-8"), _URL)
    assert len(facts) == 3  # row rác + bảng không khớp heading bị loại
    f = facts[0]
    assert f.program_name == "Khoa học máy tính"
    assert f.program_code is None
    assert f.admission_method_raw == "Điểm thi THPT"
    assert f.cutoff_year == 2025
    assert f.cutoff_score_raw == "28,25"
    assert f.subject_combinations_raw == ["A00", "A01"]
    assert f.note_raw == "Môn chính: Toán"
    assert f.source_reference.trust_level == 3
    assert facts[1].cutoff_score_raw == "27.5"
    assert facts[2].admission_method_raw == "Điểm Đánh giá Tư duy"
    assert facts[2].cutoff_score_raw == "83.9"


def test_year_filter_excludes_other_years():
    facts = Tuyensinh247CutoffParser().parse(
        _SYNTHETIC.encode("utf-8"), _URL, cutoff_year=2024,
    )
    assert facts == []


def test_returns_empty_when_no_matching_heading():
    facts = Tuyensinh247CutoffParser().parse(
        b"<html><h3>Tin tuyển sinh</h3><table><tr><th>Tiêu đề</th></tr></table></html>", _URL,
    )
    assert facts == []


def test_parses_real_fixture_snapshot():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "tsn247_bka_cutoff_2025.html"
    facts = Tuyensinh247CutoffParser().parse(fixture.read_bytes(), _URL)
    # Chỉnh ngưỡng theo snapshot thật sau Task 1 (probe 2026-06-05: ~130 ngành THPT + 3 bảng ~65 row):
    assert len(facts) >= 100
    assert {f.admission_method_raw for f in facts} == {
        "Điểm thi THPT", "Điểm Đánh giá Tư duy", "Điểm xét tuyển kết hợp", "Chứng chỉ quốc tế",
    }
    assert {f.cutoff_year for f in facts} == {2025}
    assert any("máy tính" in (f.program_name or "").lower() for f in facts)
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/ingestion/test_tuyensinh247_cutoff_parser.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement** — create `ingestion/parsers/tuyensinh247_cutoff_parser.py`:

```python
"""Tuyensinh247 cutoff (điểm chuẩn) HTML parser — Giai đoạn 2.

Trang https://diemthi.tuyensinh247.com/diem-chuan/<slug>.html: mỗi phương thức một bảng
`Tên ngành | Tổ hợp môn | Điểm chuẩn | Ghi chú` đứng sau heading h3
"Điểm chuẩn theo phương thức {X} năm {Y}". Layout chung mọi trường → parser generic;
thêm trường mới chỉ cần thêm entry initial_sources.json.

Aggregator (trust 3) — nguồn phụ bên cạnh seed chính thức (trust 5).
Trả ExtractedCutoffFact (KHÔNG phải ExtractedAdmissionFact) — vì vậy parser này chạy
qua runner `ingestion.ingest_cutoffs --source-url`, KHÔNG qua IngestionPipeline.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from ingestion.models.pipeline_models import ExtractedCutoffFact, SourceReference

logger = logging.getLogger(__name__)

# get_text(" ", strip=True) chèn space giữa các element con của h3;
# regex vẫn chịu được trường hợp dính liền ("phương thứcĐiểm thi THPTnăm2025").
_HEADING_RE = re.compile(
    r"điểm chuẩn theo phương thức\s*(.+?)\s*năm\s*(20\d{2})", re.IGNORECASE
)
_SCORE_RE = re.compile(r"^\d{1,3}([.,]\d{1,2})?$")


class Tuyensinh247CutoffParser:
    """Không kế thừa BaseSpecializedParser vì trả ExtractedCutoffFact (khác kiểu).

    Đăng ký riêng qua CUTOFF_PARSERS trong ingest_cutoffs (không vào ParserRegistry
    của pipeline chính — tránh dispatch nhầm sang đường admission facts).
    """

    parser_profile = "tuyensinh247_cutoff_html"

    def parse(
        self,
        content: bytes,
        source_url: str,
        cutoff_year: Optional[int] = None,   # filter tùy chọn; năm thật đọc từ heading
        school_id: str = "hust",
        school_name: str = "Đại học Bách khoa Hà Nội",
        trust_level: int = 3,
    ) -> List[ExtractedCutoffFact]:
        facts: List[ExtractedCutoffFact] = []
        soup = BeautifulSoup(content, "html.parser")

        for h3 in soup.find_all("h3"):
            m = _HEADING_RE.search(h3.get_text(" ", strip=True))
            if not m:
                continue
            method_raw, year = m.group(1).strip(), int(m.group(2))
            if cutoff_year is not None and year != cutoff_year:
                continue
            table = h3.find_next("table")
            if table is None:
                logger.warning(
                    "Tuyensinh247CutoffParser: heading %r không có bảng kèm theo", method_raw
                )
                continue
            facts.extend(
                self._parse_table(
                    table, method_raw, year, source_url, school_id, school_name, trust_level
                )
            )

        logger.info(
            "Tuyensinh247CutoffParser: %d cutoff facts from %s", len(facts), source_url
        )
        return facts

    def _parse_table(
        self, table, method_raw, year, source_url, school_id, school_name, trust_level
    ) -> List[ExtractedCutoffFact]:
        rows = table.find_all("tr")
        if not rows:
            return []
        header = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        col: dict[str, Optional[int]] = {"name": None, "combo": None, "score": None, "note": None}
        for i, text in enumerate(header):
            if "tên ngành" in text or "ngành" in text:
                col["name"] = col["name"] if col["name"] is not None else i
            elif "tổ hợp" in text:
                col["combo"] = i
            elif "điểm chuẩn" in text or "điểm trúng tuyển" in text:
                col["score"] = i
            elif "ghi chú" in text:
                col["note"] = i
        if col["name"] is None or col["score"] is None:
            logger.warning(
                "Tuyensinh247CutoffParser: bảng %r thiếu cột bắt buộc, header=%r",
                method_raw, header,
            )
            return []

        facts: List[ExtractedCutoffFact] = []
        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) <= col["score"]:
                continue  # row rác "Tra cứu tại..." (colspan) / divider
            score_raw = cells[col["score"]].strip()
            if not _SCORE_RE.match(score_raw):
                continue
            program_name = cells[col["name"]].strip()
            if not program_name:
                continue
            combos_text = cells[col["combo"]].strip() if col["combo"] is not None and len(cells) > col["combo"] else ""
            combos = [s.strip() for s in combos_text.split(";") if s.strip()] or None
            note = (cells[col["note"]].strip() if col["note"] is not None and len(cells) > col["note"] else "") or None

            facts.append(
                ExtractedCutoffFact(
                    school_name=school_name,
                    cutoff_year=year,
                    program_name=program_name,
                    program_code=None,  # trang không có mã xét tuyển
                    admission_method_raw=method_raw,
                    subject_combinations_raw=combos,
                    cutoff_score_raw=score_raw,
                    note_raw=note,
                    source_reference=SourceReference(
                        source_id=f"tsn247_cutoff_{school_id}_{year}",
                        source_url=source_url,
                        school_id=school_id,
                        trust_level=trust_level,
                    ),
                    confidence_score=0.85,  # aggregator — thấp hơn parser nguồn chính thức (0.9)
                    extraction_method="tuyensinh247_cutoff_parser",
                )
            )
        return facts
```

(Nhắc lại: KHÔNG sửa `base_parser.py::_auto_discover` — parser này cố ý nằm NGOÀI
ParserRegistry của pipeline chính; xem docstring trong code.)

- [ ] **Step 4: Chạy test**

Run: `python -m pytest tests/ingestion/test_tuyensinh247_cutoff_parser.py -q`
Expected: PASS (test fixture thật pass sau khi chỉnh ngưỡng assert theo snapshot ở Task 1).

- [ ] **Step 5: Commit**

```bash
git add ingestion/parsers/tuyensinh247_cutoff_parser.py tests/ingestion/test_tuyensinh247_cutoff_parser.py tests/fixtures/tsn247_bka_cutoff_2025.html
git commit -m "feat: deterministic tuyensinh247 cutoff HTML parser (4 method tables)"
```

---

### Task 3: Runner `--source-url` trong `ingest_cutoffs` + đăng ký source bookkeeping

**Files:**
- Modify: `ingestion/ingest_cutoffs.py`
- Modify: `ingestion/registry/models.py` (enum `SourceType`)
- Modify: `ingestion/registry/seeds/initial_sources.json`
- Test: `tests/ingestion/test_cutoff_seed_loader.py` (append)

- [ ] **Step 1: Viết test fail** — append vào `tests/ingestion/test_cutoff_seed_loader.py`:

```python
from ingestion.models.pipeline_models import ExtractedCutoffFact, SourceReference


def _fact(name="Khoa học máy tính", score_raw="28,25", method_raw="Điểm thi THPT"):
    return ExtractedCutoffFact(
        school_name="Đại học Bách khoa Hà Nội", cutoff_year=2025, program_name=name,
        program_code=None, admission_method_raw=method_raw,
        subject_combinations_raw=["A00", "A01"], cutoff_score_raw=score_raw,
        source_reference=SourceReference(
            source_id="tsn247_cutoff_hust_2025",
            source_url="https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html",
            school_id="hust", trust_level=3,
        ),
    )


def test_normalize_cutoff_facts_maps_and_skips(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    facts = [
        _fact(),                                            # OK — thpt_score thang 30
        _fact(method_raw="Điểm Đánh giá Tư duy", score_raw="83.9"),  # OK — thang 100
        _fact(name="Ngành Lạ"),                             # không resolve ngành → skip
        _fact(score_raw="ba mươi"),                         # điểm rác → skip
        _fact(score_raw="35"),                              # 35 > thang 30 của thpt_score → skip
        _fact(method_raw="Phương thức bí ẩn"),              # method không map được → skip
    ]
    records, skipped = ingest_cutoffs.normalize_cutoff_facts(facts)

    assert len(records) == 2
    assert records[0].program_id == "computer_science"
    assert records[0].cutoff_score == 28.25        # "28,25" → 28.25
    assert records[0].admission_method == "thpt_score"
    assert records[0].score_scale == 30.0
    assert records[0].subject_combinations == ["A00", "A01"]
    assert records[1].admission_method == "competency_test"
    assert records[1].score_scale == 100.0
    assert len(skipped) == 4


def test_main_source_url_runs_fetch_parse_save(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)

    class _FakeFetch:
        raw_content = b"<html>fixture</html>"
        http_status = 200

    monkeypatch.setattr(ingest_cutoffs, "http_fetch", lambda url, **kw: _FakeFetch())
    monkeypatch.setattr(
        type(ingest_cutoffs.CUTOFF_PARSERS["tuyensinh247_cutoff_html"]), "parse",
        lambda self, content, source_url, cutoff_year=None, **kw: [_fact()],
    )
    saved = []
    monkeypatch.setattr(ingest_cutoffs, "save_cutoff_records", lambda rs: saved.append(rs) or len(rs))

    code = ingest_cutoffs._main([
        "--source-url",
        "https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html",
        "--parser", "tuyensinh247_cutoff_html",
    ])

    assert code == 0
    assert len(saved[0]) == 1
    assert saved[0][0].source_trust_level == 3


def test_main_source_url_exit_1_when_nothing_saved(monkeypatch):
    class _FakeFetch:
        raw_content = b"<html>no table</html>"
        http_status = 200

    monkeypatch.setattr(ingest_cutoffs, "http_fetch", lambda url, **kw: _FakeFetch())
    monkeypatch.setattr(
        type(ingest_cutoffs.CUTOFF_PARSERS["tuyensinh247_cutoff_html"]), "parse",
        lambda self, content, source_url, cutoff_year=None, **kw: [],
    )

    code = ingest_cutoffs._main([
        "--source-url", "https://x", "--parser", "tuyensinh247_cutoff_html",
    ])
    assert code == 1
```

(Patch `parse` qua class attr — `type(...CUTOFF_PARSERS[...])` — vì value trong dict là instance.)

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/ingestion/test_cutoff_seed_loader.py -q`
Expected: FAIL — `normalize_cutoff_facts`/`CUTOFF_PARSERS`/`http_fetch` chưa tồn tại.

- [ ] **Step 3: Implement runner** — sửa `ingestion/ingest_cutoffs.py`:

(a) Thêm imports:

```python
from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.models.pipeline_models import ExtractedCutoffFact
from ingestion.normalization.method_mapper import map_method
from ingestion.parsers.tuyensinh247_cutoff_parser import Tuyensinh247CutoffParser
from services.profile.admission_methods import METHOD_CODES
```

(b) Thêm registry nhỏ + normalize sau `validate_entries`:

```python
CUTOFF_PARSERS = {
    Tuyensinh247CutoffParser.parser_profile: Tuyensinh247CutoffParser(),
}

# Thang điểm theo method canonical: THPT thang 30; ĐGTD/XTKH/CCQT trên tuyensinh247 thang 100.
_SCALE_BY_METHOD = {"thpt_score": 30.0}
_DEFAULT_SCALE = 100.0

_SCHOOL_NAMES = {"hust": "Đại học Bách khoa Hà Nội"}


def normalize_cutoff_facts(
    facts: List[ExtractedCutoffFact],
) -> Tuple[List[NormalizedCutoffRecord], List[str]]:
    """Đường parser: per-row skip + báo cáo (khác seed: seed phải atomic-sạch).

    Row không resolve được ngành/method/điểm rác → skip kèm lý do; caller in summary.
    """
    records: List[NormalizedCutoffRecord] = []
    skipped: List[str] = []
    for f in facts:
        school_id = f.source_reference.school_id
        program_id, canonical = map_program(f.program_name, f.program_code, school_id=school_id)
        if not program_id or program_id == f.program_code:
            skipped.append(f"{f.program_name!r}: không resolve được ngành")
            continue
        method = map_method(f.admission_method_raw, school_id=school_id) if f.admission_method_raw else None
        if method not in METHOD_CODES:
            skipped.append(f"{f.program_name!r}: phương thức {f.admission_method_raw!r} không map được")
            continue
        try:
            score = float((f.cutoff_score_raw or "").replace(",", "."))
        except ValueError:
            skipped.append(f"{f.program_name!r}: điểm {f.cutoff_score_raw!r} không phải số")
            continue
        scale = _SCALE_BY_METHOD.get(method, _DEFAULT_SCALE)
        if not (0 < score <= scale):
            skipped.append(f"{f.program_name!r}: điểm {score} ngoài (0, {scale:g}] của {method}")
            continue

        records.append(
            NormalizedCutoffRecord(
                school_id=school_id,
                program_id=program_id,
                program_name_canonical=canonical,
                program_name_raw=f.program_name,
                cutoff_year=f.cutoff_year,
                admission_method=method,
                score_scale=scale,
                cutoff_score=score,
                subject_combinations=f.subject_combinations_raw or [],
                note=f.note_raw,
                source_url=f.source_reference.source_url,
                source_trust_level=f.source_reference.trust_level,
                confidence_score=f.confidence_score,
            )
        )
    return records, skipped
```

(c) Mở rộng `_main`: thêm args + nhánh source-url (đặt TRƯỚC nhánh seed; bỏ `parser.error` cũ khi thiếu `--seed`):

```python
    parser.add_argument("--source-url", default=None, help="URL trang điểm chuẩn (đường parser)")
    parser.add_argument("--parser", default="tuyensinh247_cutoff_html", choices=sorted(CUTOFF_PARSERS),
                        help="parser profile cho --source-url")
    parser.add_argument("--year", type=int, default=None,
                        help="filter cutoff_year (đường parser; mặc định lấy mọi năm parser đọc được từ heading)")
    parser.add_argument("--trust", type=int, default=3,
                        help="trust level nguồn (đường parser; mặc định 3 — aggregator)")
```

(lưu ý: `--school` đã tồn tại từ đường seed của Plan 1 — tái dùng cho đường parser, default `hust`)

```python
    if args.source_url:
        fetch = http_fetch(args.source_url)
        if not fetch or fetch.http_status >= 400:
            print(f"LỖI fetch {args.source_url}: HTTP {getattr(fetch, 'http_status', '?')}")
            return 1
        cutoff_parser = CUTOFF_PARSERS[args.parser]
        facts = cutoff_parser.parse(
            fetch.raw_content, args.source_url, cutoff_year=args.year,
            school_id=args.school or "hust",
            school_name=_SCHOOL_NAMES.get(args.school or "hust", args.school or "hust"),
            trust_level=args.trust,
        )
        records, skipped = normalize_cutoff_facts(facts)
        for reason in skipped:
            print(f"  SKIP {reason}")
        if not records:
            print("Không có bản ghi hợp lệ nào từ nguồn — kiểm tra parser/dictionary.")
            return 1
        if args.dry_run:
            for r in records:
                print(f"  {r.school_id} {r.cutoff_year} {r.admission_method} {r.program_id} = {r.cutoff_score}")
            return 0
        saved = save_cutoff_records(records)
        print(f"Đã upsert {saved}/{len(records)} bản ghi (skip {len(skipped)} row).")
        return 0 if saved == len(records) else 2

    if not args.seed:
        parser.error("cần --seed hoặc --source-url")
```

(d) Đăng ký bookkeeping: `ingestion/registry/models.py` thêm vào enum `SourceType` (sau `PROGRAM_LISTING`):

```python
    CUTOFF_ANNOUNCEMENT = "cutoff_announcement"
```

và `ingestion/registry/seeds/initial_sources.json` thêm entry:

```json
{
  "source_id": "hust_cutoff_tsn247_2025",
  "school_id": "hust",
  "school_name": "Đại học Bách khoa Hà Nội",
  "source_type": "cutoff_announcement",
  "root_url": "https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html",
  "trust_level": 3,
  "priority": 5,
  "fetch_strategy": "http",
  "parser_profile": "tuyensinh247_cutoff_html",
  "update_frequency_hint": "yearly",
  "is_official": false,
  "active": false
}
```

(`active: false` CÓ CHỦ ĐÍCH: parser này trả `ExtractedCutoffFact`, nếu để active thì
`IngestionPipeline.run_for_school("hust")` sẽ dispatch nhầm nó vào đường admission facts.
`is_official: false` + `trust_level: 3`: aggregator — nguồn phụ, seed chính thức trust 5 vẫn thắng
khi conflict non-decision-changing.)

- [ ] **Step 4: Chạy test + chạy thật**

Run: `python -m pytest tests/ingestion/ -q`
Expected: PASS.

Run (DB up):
`python -m ingestion.ingest_cutoffs --source-url https://diemthi.tuyensinh247.com/diem-chuan/dai-hoc-bach-khoa-ha-noi-BKA.html --dry-run`
Expected: liệt kê 4 nhóm method, các ngành resolve được + SKIP list các ngành ngoài dictionary
(trang BKA có ~130 ngành, dictionary HUST hiện chỉ phủ nhóm CNTT — SKIP nhiều là ĐÚNG;
chỉ cần nhóm demo: Khoa học máy tính / Kỹ thuật máy tính / Khoa học dữ liệu... resolve được).
Sau đó chạy không `--dry-run` → upsert; row 2025 tuyensinh247 nằm CẠNH row 2025 seed chính thức
(khác `source_url` → 2 row, nền dữ liệu thật cho EC-16).

- [ ] **Step 5: Commit**

```bash
git add ingestion/ingest_cutoffs.py ingestion/registry/models.py ingestion/registry/seeds/initial_sources.json tests/ingestion/test_cutoff_seed_loader.py
git commit -m "feat: cutoff source runner (fetch/parse/normalize/save) and tsn247 source bookkeeping"
```

---

### Task 4: Khép phase — toàn suite + smoke

- [ ] **Step 1:** `python -m pytest -q` → toàn xanh.
- [ ] **Step 2:** Docker DB up: `python -m pytest tests/integration tests/e2e -q` → xanh.
- [ ] **Step 3:** Smoke web UI (`python -m uvicorn web.app:app --reload`) với 4 kịch bản EC-14/15/16/18 (điểm 26.25 / hồ sơ chạm chương trình biến động / chương trình có 2 nguồn — sau Task 3 nguồn thứ hai là tuyensinh247 thật / bất kỳ) — kiểm tra caveat năm tham chiếu xuất hiện.
- [ ] **Step 4:** Cập nhật memory `edge-case-conformance` (EC-14/15/16/17/18 → ĐẠT) + cập nhật bảng trạng thái trong index plan.
