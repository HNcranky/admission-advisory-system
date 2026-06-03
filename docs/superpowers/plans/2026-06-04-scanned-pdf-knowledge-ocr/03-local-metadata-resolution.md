# Plan 03: Local PDF Metadata Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Suy ra `{school, year}` cho mỗi PDF local theo thứ tự ưu tiên: `overrides.json` → LLM classify (text 1–2 trang đầu) → regex năm từ tên file → `school="unknown"` + WARNING (file vẫn ingest).

**Architecture:** Module nhỏ mới `ingestion/knowledge/local_metadata.py` chứa: `load_overrides(root)`, `metadata_from_override(entry)`, `year_from_filename(name)`, `resolve_metadata(first_pages_text, filename, overrides, gateway)` trả `ResolvedMetadata(school, year, warnings)`, và `build_gateway_classifier(gateway)` đóng gói thành classify-callable cho pipeline (Plan 05) inject.

**Tech Stack:** Gateway Gemini (agent `knowledge_classify` đã đăng ký ở Plan 01, `output_mode="json"`), regex `\b20\d{2}\b`, JSON file đọc bằng `pathlib`.

**Phụ thuộc:** Plan 01 (agent `knowledge_classify`). Không phụ thuộc Plan 02.

---

## Bối cảnh cho người chưa biết codebase

- `school` là **hard filter** trong `vector_search` (`services/knowledge/repository.py`) —
  classify sai school làm chunk vô hình. Vì thế school bị **ràng buộc whitelist**:
  `HUST`, `NEU`, `VNU-UET` (đồng bộ `ingestion/knowledge/registry/seeds/knowledge_sources.json`
  và intent router `services/chat/intent_router.py:95`); ngoài danh sách → `"unknown"`.
- Convention LLM: gọi `gateway.run(InferenceRequest(...))`; lỗi cứng raise `InferenceError`
  → call site phải bắt, `logger.warning`, degrade về deterministic. JSON hỏng →
  `result.parsed_data is None` (gateway đã retry trước đó) — cũng phải degrade.
- `overrides.json` nằm ở root folder knowledge (cạnh `pdf_text/`, `pdf_scanned/`), format:
  `{ "<tên-file.pdf>": {"school": "HUST", "year": 2026} }`. Người dùng sửa tay khi
  classify nhầm rồi chạy lại pipeline.

---

### Task 1: `load_overrides` + `metadata_from_override` + `year_from_filename`

**Files:**
- Create: `ingestion/knowledge/local_metadata.py`
- Test: `tests/ingestion/knowledge/test_local_metadata.py`

- [ ] **Step 1: Viết failing test**

Tạo `tests/ingestion/knowledge/test_local_metadata.py`:

```python
from types import SimpleNamespace

from ingestion.knowledge.local_metadata import (
    KNOWN_SCHOOLS,
    UNKNOWN_SCHOOL,
    ResolvedMetadata,
    build_gateway_classifier,
    load_overrides,
    metadata_from_override,
    resolve_metadata,
    year_from_filename,
)
from services.inference.models import InferenceError


def test_load_overrides_missing_file_returns_empty(tmp_path):
    assert load_overrides(tmp_path) == {}


def test_load_overrides_reads_entries(tmp_path):
    (tmp_path / "overrides.json").write_text(
        '{"de-an-hust.pdf": {"school": "HUST", "year": 2026}}', encoding="utf-8"
    )
    overrides = load_overrides(tmp_path)
    assert overrides == {"de-an-hust.pdf": {"school": "HUST", "year": 2026}}


def test_metadata_from_override_maps_fields():
    meta = metadata_from_override({"school": "NEU", "year": 2025})
    assert meta == ResolvedMetadata(school="NEU", year=2025)


def test_metadata_from_override_defaults_missing_fields():
    meta = metadata_from_override({})
    assert meta.school == UNKNOWN_SCHOOL
    assert meta.year is None


def test_year_from_filename_finds_20xx():
    assert year_from_filename("de-an-tuyen-sinh-2026-final.pdf") == 2026


def test_year_from_filename_none_when_absent():
    assert year_from_filename("quy-che.pdf") is None
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_local_metadata.py -q`
Expected: FAIL khi import — `ModuleNotFoundError: No module named 'ingestion.knowledge.local_metadata'`.

- [ ] **Step 3: Viết module (phần deterministic)**

Tạo `ingestion/knowledge/local_metadata.py`:

```python
"""Metadata resolution for locally-dropped knowledge PDFs.

Priority per NEW file: overrides.json -> LLM classify {school, year} from the
first pages' text -> year regex from the filename -> school="unknown" + WARNING
(the file is still ingested; the user adds an override and re-runs).
See docs/superpowers/specs/2026-06-04-scanned-pdf-knowledge-ocr-design.md (5.3).
"""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from services.inference.models import InferenceError, InferenceRequest

logger = logging.getLogger(__name__)

# Hard filter in vector_search — MUST stay in sync with the school codes used in
# knowledge_sources.json and the intent router. Anything else maps to "unknown".
KNOWN_SCHOOLS = ("HUST", "NEU", "VNU-UET")
UNKNOWN_SCHOOL = "unknown"

# Only the first pages go to the classifier; official cover pages name the
# school/year up front, and this caps token cost per file.
CLASSIFY_TEXT_LIMIT = 4000

_YEAR_RE = re.compile(r"\b20\d{2}\b")

CLASSIFY_SYSTEM_PROMPT = (
    "Bạn phân loại tài liệu tuyển sinh đại học Việt Nam. "
    "Chỉ trả về JSON đúng schema, không thêm lời dẫn."
)

CLASSIFY_USER_TEMPLATE = (
    "Cho tên file và nội dung 1-2 trang đầu của một tài liệu PDF tuyển sinh, "
    "xác định trường và năm tuyển sinh.\n"
    '- "school": một trong {schools}, hoặc "unknown" nếu không chắc chắn.\n'
    '- "year": năm tuyển sinh (số nguyên, ví dụ 2026), hoặc null nếu không rõ.\n'
    'Trả về JSON dạng {{"school": "...", "year": 2026}}.\n\n'
    "Tên file: {filename}\n\n"
    "Nội dung:\n{text}"
)


@dataclass
class ResolvedMetadata:
    school: str
    year: int | None
    warnings: list[str] = field(default_factory=list)


def load_overrides(root: Path) -> dict:
    """Read <root>/overrides.json: {"<filename>": {"school": "...", "year": 2026}}."""
    path = Path(root) / "overrides.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def metadata_from_override(entry: dict) -> ResolvedMetadata:
    return ResolvedMetadata(
        school=entry.get("school", UNKNOWN_SCHOOL),
        year=entry.get("year"),
    )


def year_from_filename(filename: str) -> int | None:
    m = _YEAR_RE.search(filename)
    return int(m.group(0)) if m else None
```

- [ ] **Step 4: Chạy test, xác nhận pass (các test resolve/classifier vẫn fail import — sẽ xanh ở Task 2/3)**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_local_metadata.py -q`
Expected: FAIL import vì `resolve_metadata`/`build_gateway_classifier` chưa tồn tại. Tạm thời comment 2 import đó **hoặc** (gọn hơn) viết luôn stub ở cuối module:

```python
def resolve_metadata(first_pages_text, filename, overrides, gateway):
    raise NotImplementedError


def build_gateway_classifier(gateway=None):
    raise NotImplementedError
```

Run lại: Expected — 6 test Task 1 PASS, chưa có test nào đụng stub.

- [ ] **Step 5: Commit**

```powershell
git add ingestion\knowledge\local_metadata.py tests\ingestion\knowledge\test_local_metadata.py
git commit -m "feat: add overrides and filename-year helpers for local PDF metadata"
```

---

### Task 2: `resolve_metadata` — override thắng, classify, whitelist, degrade

**Files:**
- Modify: `ingestion/knowledge/local_metadata.py` (thay stub `resolve_metadata`)
- Test: `tests/ingestion/knowledge/test_local_metadata.py` (thêm vào cuối file)

- [ ] **Step 1: Viết failing test**

Thêm vào cuối `tests/ingestion/knowledge/test_local_metadata.py`:

```python
# --- resolve_metadata -----------------------------------------------------------

class FakeGateway:
    """Gateway giả: trả parsed_data cho sẵn hoặc raise InferenceError."""

    def __init__(self, parsed=None, exc=None):
        self.requests = []
        self._parsed = parsed
        self._exc = exc

    def run(self, request):
        self.requests.append(request)
        if self._exc is not None:
            raise self._exc
        return SimpleNamespace(parsed_data=self._parsed, content="")


def test_override_wins_without_llm_call():
    gw = FakeGateway(parsed={"school": "HUST", "year": 2026})
    overrides = {"x.pdf": {"school": "NEU", "year": 2024}}

    meta = resolve_metadata("text trang đầu", "x.pdf", overrides, gw)

    assert meta.school == "NEU" and meta.year == 2024
    assert gw.requests == []                  # không tốn call classify


def test_classify_returns_school_and_year():
    gw = FakeGateway(parsed={"school": "VNU-UET", "year": 2026})

    meta = resolve_metadata("ĐẠI HỌC CÔNG NGHỆ ...", "de-an.pdf", {}, gw)

    assert meta.school == "VNU-UET" and meta.year == 2026
    assert meta.warnings == []
    req = gw.requests[0]
    assert req.agent_name == "knowledge_classify"
    assert req.task_type == "local_pdf_metadata"
    assert req.output_mode == "json"
    assert "de-an.pdf" in req.user_prompt
    assert "ĐẠI HỌC CÔNG NGHỆ" in req.user_prompt


def test_school_outside_whitelist_becomes_unknown_with_warning():
    gw = FakeGateway(parsed={"school": "FTU", "year": 2026})

    meta = resolve_metadata("text", "ftu.pdf", {}, gw)

    assert meta.school == UNKNOWN_SCHOOL
    assert meta.year == 2026                  # year hợp lệ vẫn giữ
    assert any("ftu.pdf" in w and "overrides.json" in w for w in meta.warnings)


def test_year_falls_back_to_filename_when_classify_unsure():
    gw = FakeGateway(parsed={"school": "HUST", "year": None})

    meta = resolve_metadata("text", "de-an-2026.pdf", {}, gw)

    assert meta.school == "HUST"
    assert meta.year == 2026                  # regex \b20\d{2}\b từ tên file


def test_year_string_from_llm_is_coerced_to_int():
    gw = FakeGateway(parsed={"school": "HUST", "year": "2025"})

    meta = resolve_metadata("text", "x.pdf", {}, gw)

    assert meta.year == 2025


def test_inference_error_degrades_to_unknown_school():
    gw = FakeGateway(exc=InferenceError("boom"))

    meta = resolve_metadata("text", "de-an-2026.pdf", {}, gw)

    assert meta.school == UNKNOWN_SCHOOL
    assert meta.year == 2026                  # filename fallback vẫn chạy
    assert len(meta.warnings) == 1


def test_structure_failure_parsed_none_degrades_like_empty():
    gw = FakeGateway(parsed=None)             # gateway đã hết retry, JSON vẫn hỏng

    meta = resolve_metadata("text", "x.pdf", {}, gw)

    assert meta.school == UNKNOWN_SCHOOL
    assert meta.year is None
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_local_metadata.py -q`
Expected: các test mới FAILED với `NotImplementedError`.

- [ ] **Step 3: Thay stub bằng implementation**

Thay stub `resolve_metadata` trong `ingestion/knowledge/local_metadata.py`:

```python
def resolve_metadata(
    first_pages_text: str,
    filename: str,
    overrides: dict,
    gateway,
) -> ResolvedMetadata:
    """Resolve {school, year} for one local PDF (see module docstring for priority)."""
    entry = overrides.get(filename)
    if entry is not None:
        return metadata_from_override(entry)

    data: dict = {}
    try:
        result = gateway.run(InferenceRequest(
            agent_name="knowledge_classify",
            task_type="local_pdf_metadata",
            system_prompt=CLASSIFY_SYSTEM_PROMPT,
            user_prompt=CLASSIFY_USER_TEMPLATE.format(
                schools=", ".join(KNOWN_SCHOOLS),
                filename=filename,
                text=first_pages_text[:CLASSIFY_TEXT_LIMIT],
            ),
            output_mode="json",
            temperature=0.0,
        ))
        data = result.parsed_data or {}
    except InferenceError as exc:
        # Degrade gracefully: the file still ingests with school="unknown".
        logger.warning("Metadata classify failed for %s: %r", filename, exc)

    school = data.get("school")
    if school not in KNOWN_SCHOOLS:
        school = UNKNOWN_SCHOOL
    try:
        year = int(data.get("year"))
    except (TypeError, ValueError):
        year = year_from_filename(filename)

    warnings: list[str] = []
    if school == UNKNOWN_SCHOOL:
        warnings.append(
            f"{filename}: school=unknown — thêm entry vào overrides.json rồi chạy lại"
        )
    return ResolvedMetadata(school=school, year=year, warnings=warnings)
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_local_metadata.py -q`
Expected: tất cả PASS (trừ test `build_gateway_classifier` chưa viết — Task 3).

- [ ] **Step 5: Commit**

```powershell
git add ingestion\knowledge\local_metadata.py tests\ingestion\knowledge\test_local_metadata.py
git commit -m "feat: resolve local PDF school/year via overrides, LLM classify, filename fallback"
```

---

### Task 3: `build_gateway_classifier` — đóng gói cho pipeline inject

**Files:**
- Modify: `ingestion/knowledge/local_metadata.py` (thay stub `build_gateway_classifier`)
- Test: `tests/ingestion/knowledge/test_local_metadata.py` (thêm vào cuối file)

- [ ] **Step 1: Viết failing test**

```python
# --- build_gateway_classifier -----------------------------------------------------

def test_build_gateway_classifier_binds_gateway():
    gw = FakeGateway(parsed={"school": "HUST", "year": 2026})
    classify = build_gateway_classifier(gateway=gw)

    meta = classify("text trang 1", "x.pdf", {})

    assert meta == ResolvedMetadata(school="HUST", year=2026)
    assert len(gw.requests) == 1


def test_build_gateway_classifier_callable_honors_overrides():
    gw = FakeGateway(parsed={"school": "HUST", "year": 2026})
    classify = build_gateway_classifier(gateway=gw)

    meta = classify("text", "x.pdf", {"x.pdf": {"school": "NEU", "year": 2024}})

    assert meta.school == "NEU"
    assert gw.requests == []
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_local_metadata.py -q -k classifier`
Expected: 2 FAILED với `NotImplementedError`.

- [ ] **Step 3: Thay stub bằng implementation**

```python
def build_gateway_classifier(gateway=None):
    """Classify callable for the pipeline:
    (first_pages_text, filename, overrides) -> ResolvedMetadata."""
    from services.inference.factory import build_default_gateway

    gw = gateway if gateway is not None else build_default_gateway()

    def _classify(first_pages_text: str, filename: str, overrides: dict) -> ResolvedMetadata:
        return resolve_metadata(first_pages_text, filename, overrides, gw)

    return _classify
```

(Import `build_default_gateway` để lazy bên trong hàm — giữ module import nhẹ, cùng style `build_gateway_ocr` ở Plan 02.)

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_local_metadata.py -q`
Expected: tất cả PASS.

- [ ] **Step 5: Commit**

```powershell
git add ingestion\knowledge\local_metadata.py tests\ingestion\knowledge\test_local_metadata.py
git commit -m "feat: add gateway-bound classifier factory for local PDF metadata"
```

---

## Định nghĩa hoàn thành (Plan 03)

- Override theo tên file thắng tuyệt đối (không call LLM).
- Classify trả school ngoài `KNOWN_SCHOOLS` → `"unknown"` + WARNING gợi ý `overrides.json`.
- Year ưu tiên LLM (coerce string→int), fallback regex tên file, cuối cùng `None`.
- `InferenceError` / `parsed_data=None` không làm vỡ ingest — degrade về `"unknown"`.
- `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_local_metadata.py -q` xanh toàn bộ.
