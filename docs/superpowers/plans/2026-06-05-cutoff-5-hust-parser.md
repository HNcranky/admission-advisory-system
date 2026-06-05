# Cutoff Plan 5 — Parser trang điểm chuẩn HUST (proof-of-automation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Một parser deterministic `hust_cutoff_html` parse bảng điểm chuẩn 2025 trên `ts.hust.edu.vn` thành `ExtractedCutoffFact`, chạy qua runner `ingest_cutoffs --source-url` (fetch → parse → normalize → save), chứng minh đường tự động hoá bên cạnh seed.

**Architecture:** Template đúng `hust_announcement_html_parser` (BeautifulSoup, detect bảng theo header, map cột theo text). Runner nhận URL + tham số tường minh (`--source-url --parser --school --year --trust`) thay vì đi qua `IngestionPipeline` — pipeline chính expect `ExtractedAdmissionFact`, trộn fact type sẽ vỡ normalizer. Source vẫn được đăng ký vào registry để bookkeeping nhưng `active: false` để `run_for_school`/`run_all_schools` không nhặt nhầm.

**Tech Stack:** BeautifulSoup, pytest fixture HTML tĩnh.

**Phụ thuộc:** Plan 1 (models, `save_cutoff_records`, CLI khung).

---

### Task 1: Probe trang thật + fixture

**Files:**
- Create: `tests/fixtures/hust_cutoff_2025.html`

- [ ] **Step 1: Tìm URL trang công bố điểm chuẩn 2025 của HUST** — WebSearch `"điểm chuẩn" 2025 site:ts.hust.edu.vn` (hoặc trang "tra cứu điểm chuẩn"). Ghi lại URL chính xác.
- [ ] **Step 2: Probe cấu trúc bảng** — viết nhanh `scripts/_probe_hust_cutoff.py` theo pattern `scripts/hust_preflight_inspect.py`: fetch URL (lưu ý `ADVISORY_FETCH_VERIFY_SSL` mặc định off), in `table` headers + 3 row đầu. Xác nhận: cột tên ngành/mã ngành/điểm chuẩn nằm ở đâu, header chứa cụm gì ("Điểm chuẩn", "Điểm trúng tuyển"...).
- [ ] **Step 3: Snapshot fixture** — lưu HTML trang thật vào `tests/fixtures/hust_cutoff_2025.html` (cắt gọn phần ngoài bảng nếu file quá lớn, GIỮ NGUYÊN bảng + header). Nếu trang thật là PDF/ảnh (không phải HTML table) → dừng task, báo lại để đổi target (thử trang VNU-UET hoặc trang năm khác); KHÔNG cố OCR trong phase này.

---

### Task 2: Parser `hust_cutoff_html`

**Files:**
- Create: `ingestion/parsers/hust_cutoff_html_parser.py`
- Test: `tests/ingestion/test_hust_cutoff_html_parser.py`

(KHÔNG sửa `base_parser.py` — parser này cố ý nằm ngoài `ParserRegistry` của pipeline
chính vì trả `ExtractedCutoffFact`; đăng ký qua `CUTOFF_PARSERS` trong `ingest_cutoffs` ở Task 3.)

- [ ] **Step 1: Viết test fail** — create `tests/ingestion/test_hust_cutoff_html_parser.py`. Test 1 dùng fixture synthetic (deterministic, commit kèm test); test 2 dùng fixture thật từ Task 1:

```python
from pathlib import Path

from ingestion.parsers.hust_cutoff_html_parser import HustCutoffHtmlParser

_SYNTHETIC = """
<html><body><table>
  <tr><th>TT</th><th>Mã xét tuyển</th><th>Chương trình/ngành</th><th>Điểm chuẩn</th></tr>
  <tr><td>1</td><td>IT1</td><td>Khoa học máy tính</td><td>28,25</td></tr>
  <tr><td>2</td><td>IT2</td><td>Kỹ thuật máy tính</td><td>27.50</td></tr>
  <tr><td colspan="4">A. CHƯƠNG TRÌNH CHUẨN</td></tr>
  <tr><td></td><td></td><td>Ghi chú</td><td>—</td></tr>
</table></body></html>
"""


def test_parses_synthetic_cutoff_table():
    facts = HustCutoffHtmlParser().parse(
        _SYNTHETIC.encode("utf-8"), "https://ts.hust.edu.vn/dc-2025", cutoff_year=2025,
    )
    assert len(facts) == 2
    f = facts[0]
    assert f.program_name == "Khoa học máy tính"
    assert f.program_code == "IT1"
    assert f.cutoff_score_raw == "28,25"
    assert f.cutoff_year == 2025
    assert f.source_reference.trust_level == 5
    assert facts[1].cutoff_score_raw == "27.50"


def test_parses_real_fixture_snapshot():
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "hust_cutoff_2025.html"
    facts = HustCutoffHtmlParser().parse(
        fixture.read_bytes(), "https://ts.hust.edu.vn/dc-2025", cutoff_year=2025,
    )
    # Sau Task 1, chỉnh 2 assert này theo trang thật (số ngành + một ngành biết trước):
    assert len(facts) >= 10
    assert any("máy tính" in (f.program_name or "").lower() for f in facts)


def test_returns_empty_when_no_cutoff_table():
    facts = HustCutoffHtmlParser().parse(
        b"<html><table><tr><th>Doanh thu</th></tr></table></html>",
        "https://x", cutoff_year=2025,
    )
    assert facts == []
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/ingestion/test_hust_cutoff_html_parser.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement** — create `ingestion/parsers/hust_cutoff_html_parser.py`:

```python
"""HUST cutoff (điểm chuẩn) announcement HTML parser — Giai đoạn 2.

Bảng điểm chuẩn: header chứa "Điểm chuẩn"/"Điểm trúng tuyển"; mỗi data row có
mã xét tuyển (vd IT1), tên chương trình và điểm (thang 30, "28,25" hoặc "28.25").
Trả ExtractedCutoffFact (KHÔNG phải ExtractedAdmissionFact) — vì vậy parser này
chạy qua runner `ingestion.ingest_cutoffs --source-url`, KHÔNG qua IngestionPipeline.

Sau khi probe trang thật (Plan 5 Task 1), chỉnh _HEADER_HINTS / map cột nếu
cấu trúc thực tế khác synthetic fixture.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from ingestion.models.pipeline_models import ExtractedCutoffFact, SourceReference

logger = logging.getLogger(__name__)

_SCORE_RE = re.compile(r"^\d{1,2}[.,]\d{1,2}$|^\d{1,2}$")
_HEADER_HINTS = ("điểm chuẩn", "điểm trúng tuyển")


def _is_cutoff_table(table) -> bool:
    rows = table.find_all("tr")
    if not rows:
        return False
    header_text = " ".join(
        c.get_text(" ", strip=True) for c in rows[0].find_all(["th", "td"])
    ).lower()
    return any(hint in header_text for hint in _HEADER_HINTS)


class HustCutoffHtmlParser:
    """Không kế thừa BaseSpecializedParser vì trả ExtractedCutoffFact (khác kiểu).

    Đăng ký riêng qua CUTOFF_PARSERS trong ingest_cutoffs (không vào ParserRegistry
    của pipeline chính — tránh dispatch nhầm sang đường admission facts).
    """

    parser_profile = "hust_cutoff_html"

    def parse(
        self,
        content: bytes,
        source_url: str,
        cutoff_year: int,
        school_id: str = "hust",
        school_name: str = "Đại học Bách khoa Hà Nội",
        trust_level: int = 5,
    ) -> List[ExtractedCutoffFact]:
        facts: List[ExtractedCutoffFact] = []
        soup = BeautifulSoup(content, "html.parser")

        table = next((t for t in soup.find_all("table") if _is_cutoff_table(t)), None)
        if table is None:
            logger.warning("HustCutoffHtmlParser: cutoff table not found in %s", source_url)
            return facts

        rows = table.find_all("tr")
        header = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        col_idx: dict[str, Optional[int]] = {"name": None, "code": None, "score": None}
        for i, text in enumerate(header):
            if any(hint in text for hint in _HEADER_HINTS):
                col_idx["score"] = i
            elif "mã" in text:
                col_idx["code"] = i
            elif "ngành" in text or "chương trình" in text:
                col_idx["name"] = i
        if col_idx["name"] is None or col_idx["score"] is None:
            logger.warning("HustCutoffHtmlParser: required columns missing, header=%r", header)
            return facts

        max_idx = max(i for i in col_idx.values() if i is not None)
        for tr in rows[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) <= max_idx:
                continue  # divider row
            score_raw = cells[col_idx["score"]].strip()
            if not _SCORE_RE.match(score_raw):
                continue  # totals/ghi chú/row rác
            program_name = cells[col_idx["name"]].strip()
            if not program_name:
                continue
            program_code = (
                cells[col_idx["code"]].strip() if col_idx["code"] is not None else None
            ) or None

            facts.append(
                ExtractedCutoffFact(
                    school_name=school_name,
                    cutoff_year=cutoff_year,
                    program_name=program_name,
                    program_code=program_code,
                    admission_method_raw="Xét điểm thi TN THPT",
                    cutoff_score_raw=score_raw,
                    source_reference=SourceReference(
                        source_id=f"hust_cutoff_{cutoff_year}",
                        source_url=source_url,
                        school_id=school_id,
                        trust_level=trust_level,
                    ),
                    confidence_score=0.9,
                    extraction_method="hust_cutoff_html_parser",
                )
            )

        logger.info("HustCutoffHtmlParser: %d cutoff facts from %s", len(facts), source_url)
        return facts
```

(Nhắc lại: KHÔNG sửa `base_parser.py::_auto_discover` — parser này cố ý nằm NGOÀI
ParserRegistry của pipeline chính; xem docstring trong code.)

- [ ] **Step 4: Chạy test**

Run: `python -m pytest tests/ingestion/test_hust_cutoff_html_parser.py -q`
Expected: PASS (test fixture thật pass sau khi chỉnh assert theo trang thật ở Task 1).

- [ ] **Step 5: Commit**

```bash
git add ingestion/parsers/hust_cutoff_html_parser.py tests/ingestion/test_hust_cutoff_html_parser.py tests/fixtures/hust_cutoff_2025.html
git commit -m "feat: deterministic HUST cutoff announcement HTML parser"
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


def _fact(name="Khoa học máy tính", code="IT1", score_raw="28,25"):
    return ExtractedCutoffFact(
        school_name="HUST", cutoff_year=2025, program_name=name, program_code=code,
        admission_method_raw="Xét điểm thi TN THPT", cutoff_score_raw=score_raw,
        source_reference=SourceReference(
            source_id="hust_cutoff_2025", source_url="https://ts.hust.edu.vn/dc-2025",
            school_id="hust", trust_level=5,
        ),
    )


def test_normalize_cutoff_facts_maps_and_skips(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)
    facts = [
        _fact(),                                   # OK
        _fact(name="Ngành Lạ", code="XX9"),        # không resolve → skip
        _fact(score_raw="ba mươi"),                # điểm rác → skip
    ]
    records, skipped = ingest_cutoffs.normalize_cutoff_facts(facts)

    assert len(records) == 1
    assert records[0].program_id == "computer_science"
    assert records[0].cutoff_score == 28.25        # "28,25" → 28.25
    assert records[0].admission_method == "thpt_score"
    assert len(skipped) == 2


def test_main_source_url_runs_fetch_parse_save(monkeypatch):
    monkeypatch.setattr(ingest_cutoffs, "map_program", _fake_map_program)

    class _FakeFetch:
        raw_content = b"<html>fixture</html>"
        http_status = 200

    monkeypatch.setattr(ingest_cutoffs, "http_fetch", lambda url, **kw: _FakeFetch())
    monkeypatch.setattr(
        ingest_cutoffs.CUTOFF_PARSERS["hust_cutoff_html"], "parse",
        lambda self, content, source_url, cutoff_year, **kw: [_fact()],
    )
    saved = []
    monkeypatch.setattr(ingest_cutoffs, "save_cutoff_records", lambda rs: saved.append(rs) or len(rs))

    code = ingest_cutoffs._main([
        "--source-url", "https://ts.hust.edu.vn/dc-2025",
        "--parser", "hust_cutoff_html", "--year", "2025",
    ])

    assert code == 0
    assert len(saved[0]) == 1


def test_main_source_url_exit_1_when_nothing_saved(monkeypatch):
    class _FakeFetch:
        raw_content = b"<html>no table</html>"
        http_status = 200

    monkeypatch.setattr(ingest_cutoffs, "http_fetch", lambda url, **kw: _FakeFetch())
    monkeypatch.setattr(
        ingest_cutoffs.CUTOFF_PARSERS["hust_cutoff_html"], "parse",
        lambda self, content, source_url, cutoff_year, **kw: [],
    )

    code = ingest_cutoffs._main([
        "--source-url", "https://x", "--parser", "hust_cutoff_html", "--year", "2025",
    ])
    assert code == 1
```

Lưu ý monkeypatch method trên instance trong dict `CUTOFF_PARSERS`: patch kiểu unbound
(`lambda self, ...`) cần `HustCutoffHtmlParser.parse` — đơn giản hơn: patch class attr:
`monkeypatch.setattr(type(ingest_cutoffs.CUTOFF_PARSERS["hust_cutoff_html"]), "parse", lambda self, content, source_url, cutoff_year, **kw: [_fact()])`. Dùng dạng này trong cả 2 test.

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/ingestion/test_cutoff_seed_loader.py -q`
Expected: FAIL — `normalize_cutoff_facts`/`CUTOFF_PARSERS`/`http_fetch` chưa tồn tại.

- [ ] **Step 3: Implement runner** — sửa `ingestion/ingest_cutoffs.py`:

(a) Thêm imports:

```python
from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.models.pipeline_models import ExtractedCutoffFact
from ingestion.parsers.hust_cutoff_html_parser import HustCutoffHtmlParser
from services.profile.admission_methods import parse_admission_method
```

(b) Thêm registry nhỏ + normalize sau `validate_entries`:

```python
CUTOFF_PARSERS = {
    HustCutoffHtmlParser.parser_profile: HustCutoffHtmlParser(),
}


def normalize_cutoff_facts(
    facts: List[ExtractedCutoffFact], default_method: str = "thpt_score",
) -> Tuple[List[NormalizedCutoffRecord], List[str]]:
    """Đường parser: per-row skip + báo cáo (khác seed: seed phải atomic-sạch).

    Row không resolve được ngành/điểm rác → skip kèm lý do; caller in summary.
    """
    records: List[NormalizedCutoffRecord] = []
    skipped: List[str] = []
    for f in facts:
        school_id = f.source_reference.school_id
        program_id, canonical = map_program(f.program_name, f.program_code, school_id=school_id)
        if not program_id or program_id == f.program_code:
            skipped.append(f"{f.program_name!r}: không resolve được ngành")
            continue
        try:
            score = float((f.cutoff_score_raw or "").replace(",", "."))
        except ValueError:
            skipped.append(f"{f.program_name!r}: điểm {f.cutoff_score_raw!r} không phải số")
            continue
        if not (0 < score <= 30):
            skipped.append(f"{f.program_name!r}: điểm {score} ngoài (0, 30]")
            continue
        method = (
            parse_admission_method(f.admission_method_raw) if f.admission_method_raw else None
        ) or default_method

        records.append(
            NormalizedCutoffRecord(
                school_id=school_id,
                program_id=program_id,
                program_name_canonical=canonical,
                program_name_raw=f.program_name,
                cutoff_year=f.cutoff_year,
                admission_method=method,
                score_scale=30.0,
                cutoff_score=score,
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
    parser.add_argument("--parser", default="hust_cutoff_html", choices=sorted(CUTOFF_PARSERS),
                        help="parser profile cho --source-url")
    parser.add_argument("--year", type=int, default=None, help="cutoff_year của trang (bắt buộc với --source-url)")
    parser.add_argument("--trust", type=int, default=5, help="trust level nguồn (đường parser)")
```

```python
    if args.source_url:
        if not args.year:
            parser.error("--source-url cần --year")
        fetch = http_fetch(args.source_url)
        if not fetch or fetch.http_status >= 400:
            print(f"LỖI fetch {args.source_url}: HTTP {getattr(fetch, 'http_status', '?')}")
            return 1
        cutoff_parser = CUTOFF_PARSERS[args.parser]
        facts = cutoff_parser.parse(
            fetch.raw_content, args.source_url, cutoff_year=args.year, trust_level=args.trust,
        )
        records, skipped = normalize_cutoff_facts(facts)
        for reason in skipped:
            print(f"  SKIP {reason}")
        if not records:
            print("Không có bản ghi hợp lệ nào từ nguồn — kiểm tra parser/dictionary.")
            return 1
        if args.dry_run:
            for r in records:
                print(f"  {r.school_id} {r.cutoff_year} {r.program_id} = {r.cutoff_score}")
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

và `ingestion/registry/seeds/initial_sources.json` thêm entry (điền `root_url` thật từ Task 1):

```json
{
  "source_id": "hust_cutoff_2025",
  "school_id": "hust",
  "school_name": "Đại học Bách khoa Hà Nội",
  "source_type": "cutoff_announcement",
  "root_url": "<URL thật từ Task 1>",
  "trust_level": 5,
  "priority": 5,
  "fetch_strategy": "http",
  "parser_profile": "hust_cutoff_html",
  "update_frequency_hint": "yearly",
  "is_official": true,
  "active": false
}
```

(`active: false` CÓ CHỦ ĐÍCH: parser này trả `ExtractedCutoffFact`, nếu để active thì
`IngestionPipeline.run_for_school("hust")` sẽ dispatch nhầm nó vào đường admission facts.)

- [ ] **Step 4: Chạy test + chạy thật**

Run: `python -m pytest tests/ingestion/ -q`
Expected: PASS.

Run (DB up): `python -m ingestion.ingest_cutoffs --source-url <URL thật> --year 2025 --dry-run`
Expected: liệt kê các ngành resolve được + SKIP list các ngành ngoài dictionary. Sau đó chạy không `--dry-run` → upsert; các giá trị trùng seed (cùng source_url) chỉ update, không nhân đôi.

- [ ] **Step 5: Commit**

```bash
git add ingestion/ingest_cutoffs.py ingestion/registry/models.py ingestion/registry/seeds/initial_sources.json tests/ingestion/test_cutoff_seed_loader.py
git commit -m "feat: cutoff source runner (fetch/parse/normalize/save) and source bookkeeping"
```

---

### Task 4: Khép phase — toàn suite + smoke

- [ ] **Step 1:** `python -m pytest -q` → toàn xanh.
- [ ] **Step 2:** Docker DB up: `python -m pytest tests/integration tests/e2e -q` → xanh.
- [ ] **Step 3:** Smoke web UI (`python -m uvicorn web.app:app --reload`) với 4 kịch bản EC-14/15/16/18 (điểm 26.25 / hồ sơ chạm chương trình biến động / chương trình có 2 nguồn seed / bất kỳ) — kiểm tra caveat năm tham chiếu xuất hiện.
- [ ] **Step 4:** Cập nhật memory `edge-case-conformance` (EC-14/15/16/17/18 → ĐẠT) + cập nhật bảng trạng thái trong index plan.
