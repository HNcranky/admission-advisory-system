# Plan 02: Hybrid PDF Extractor + Gemini OCR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Module mới `ingestion/knowledge/pdf_ocr.py`: mỗi trang PDF — text layer ≥ 50 ký tự dùng luôn, trang ảnh render PNG ~200 DPI (PyMuPDF) rồi OCR qua Gemini vision; trang fail không chặn trang khác; cả file không có chữ nào thì raise.

**Architecture:** `extract_pages_hybrid(content, ocr, render)` nhận OCR callable và render callable (injectable cho test). OCR mặc định `build_gateway_ocr()` tạo closure gọi `gateway.run(...)` với `media=[("image/png", png)]` (cần Plan 01). Kết quả là `HybridPagesResult` có per-page method + thống kê, adapter `to_page_tuples()` khớp shape `pages_to_marked_text` sẵn có.

**Tech Stack:** `pdfplumber` (text layer, đã có), `pymupdf` (render, **dependency mới — pip-only**), gateway Gemini (Plan 01).

**Phụ thuộc:** Plan 01 (field `media` + agent `knowledge_ocr`).

---

## Bối cảnh cho người chưa biết codebase

- Luồng knowledge hiện tại đọc PDF bằng `ingestion/knowledge/pdf_pages.py::extract_pages`
  (pdfplumber) → trang scan trả `""` → biến mất không cảnh báo. Module mới này là bản
  thay thế **cho luồng local-dir** (Plan 05); `pdf_pages.py` giữ nguyên cho luồng URL.
- Ngưỡng 50 ký tự là bản per-page của heuristic `_refine_pdf_type`
  (`ingestion/router/document_router.py:105`).
- Convention degrade gracefully: bắt `InferenceError` (từ `services/inference/models.py`),
  `logger.warning`, đi tiếp. **Nhưng** nếu cả file rỗng phải raise — nếu cứ
  `mark_ingested` thì content-hash skip sẽ giấu lỗi vĩnh viễn (bug gốc của spec).
- Test style của repo: fake/inject, không network (xem `tests/ingestion/knowledge/test_pipeline.py`).

---

### Task 1: Thêm dependency `pymupdf`

**Files:**
- Modify: `requirements.txt:10-12` (section `# PDF`)

- [ ] **Step 1: Cài và xác nhận import được**

```powershell
.\.venv\Scripts\python.exe -m pip install pymupdf
.\.venv\Scripts\python.exe -c "import pymupdf; print(pymupdf.__version__)"
```

Expected: in ra version (ví dụ `1.26.7`).

- [ ] **Step 2: Pin vào requirements.txt**

Trong `requirements.txt`, section `# PDF` thành:

```text
# PDF
pdfminer.six==20251230
pdfplumber==0.11.9
pymupdf==1.26.7
```

> Nếu Step 1 in ra version khác `1.26.7`, pin đúng version đã cài ở Step 1.

- [ ] **Step 3: Commit**

```powershell
git add requirements.txt
git commit -m "chore: add pymupdf for PDF page rendering"
```

---

### Task 2: Skeleton module — dataclass + `_extract_text_layers` + happy path

**Files:**
- Create: `ingestion/knowledge/pdf_ocr.py`
- Test: `tests/ingestion/knowledge/test_pdf_ocr.py`

- [ ] **Step 1: Viết failing test**

Tạo `tests/ingestion/knowledge/test_pdf_ocr.py`:

```python
from types import SimpleNamespace

import pytest

from ingestion.knowledge import pdf_ocr
from ingestion.knowledge.pdf_ocr import (
    TEXT_LAYER_MIN_CHARS,
    HybridExtractionError,
    build_gateway_ocr,
    extract_pages_hybrid,
)
from services.inference.models import InferenceError

LONG = "A" * TEXT_LAYER_MIN_CHARS          # đúng ngưỡng → dùng text layer
SHORT = "B" * (TEXT_LAYER_MIN_CHARS - 1)   # dưới ngưỡng 1 ký tự → OCR


class FakeOCR:
    """OCR giả: đếm call, có thể raise InferenceError theo thứ tự call."""

    def __init__(self, text="OCR MARKDOWN", exc_on=()):
        self.calls = []
        self.text = text
        self.exc_on = set(exc_on)

    def __call__(self, png_bytes):
        self.calls.append(png_bytes)
        if len(self.calls) in self.exc_on:
            raise InferenceError("quota exhausted")
        return self.text


def _fake_render(content, page_no):
    return f"PNG-{page_no}".encode()


def _patch_layers(monkeypatch, layers):
    """Thay pdfplumber bằng list text layer cho sẵn (mỗi phần tử = 1 trang)."""
    monkeypatch.setattr(pdf_ocr, "_extract_text_layers", lambda content: layers)


def test_text_layer_page_uses_layer_and_skips_ocr(monkeypatch):
    _patch_layers(monkeypatch, [LONG])
    ocr = FakeOCR()

    result = extract_pages_hybrid(b"%PDF", ocr, render=_fake_render)

    assert ocr.calls == []                    # trang text thật không tốn call OCR nào
    assert result.pages_text == 1 and result.pages_ocr == 0 and result.pages_failed == 0
    assert result.pages[0].method == "text_layer"
    assert result.pages[0].text == LONG
    assert result.pages[0].page_no == 1


def test_short_page_is_rendered_and_ocrd(monkeypatch):
    _patch_layers(monkeypatch, [""])
    ocr = FakeOCR(text="  # Trang OCR  ")

    result = extract_pages_hybrid(b"%PDF", ocr, render=_fake_render)

    assert ocr.calls == [b"PNG-1"]            # đầu ra render là đầu vào OCR
    assert result.pages[0].method == "ocr"
    assert result.pages[0].text == "# Trang OCR"   # đã strip
    assert result.pages_ocr == 1


def test_threshold_is_50_chars_after_strip(monkeypatch):
    # Trang 3 dài đủ nhưng bọc whitespace → strip xong vẫn đạt ngưỡng.
    _patch_layers(monkeypatch, [LONG, SHORT, "   " + LONG + "   "])
    ocr = FakeOCR()

    result = extract_pages_hybrid(b"%PDF", ocr, render=_fake_render)

    assert [p.method for p in result.pages] == ["text_layer", "ocr", "text_layer"]


def test_to_page_tuples_matches_pages_to_marked_text_shape(monkeypatch):
    _patch_layers(monkeypatch, [LONG])

    result = extract_pages_hybrid(b"%PDF", FakeOCR(), render=_fake_render)

    assert result.to_page_tuples() == [(1, LONG)]
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_pdf_ocr.py -q`
Expected: FAIL ngay khi import — `ModuleNotFoundError: No module named 'ingestion.knowledge.pdf_ocr'`.

- [ ] **Step 3: Viết module**

Tạo `ingestion/knowledge/pdf_ocr.py`:

```python
"""Hybrid per-page text extraction for knowledge PDFs (text layer + Gemini OCR).

Pages whose pdfplumber text layer is long enough are used as-is; image-only
pages are rendered to PNG (PyMuPDF, ~200 DPI) and OCR'd through the inference
gateway. See docs/superpowers/specs/2026-06-04-scanned-pdf-knowledge-ocr-design.md.
"""
import io
import logging
from dataclasses import dataclass
from typing import Callable

import pdfplumber

from services.inference.models import InferenceError, InferenceRequest

logger = logging.getLogger(__name__)

# Per-page version of the document_router._refine_pdf_type heuristic: a page
# whose stripped text layer is at least this long needs no OCR.
TEXT_LAYER_MIN_CHARS = 50

# PyMuPDF renders at 72 DPI by default; scale to ~200 DPI for legible OCR input.
RENDER_ZOOM = 200 / 72

OCR_SYSTEM_PROMPT = "Bạn là công cụ OCR tài liệu tuyển sinh đại học tiếng Việt."

OCR_USER_PROMPT = (
    "Phiên âm toàn bộ nội dung trang tài liệu sang markdown tiếng Việt. "
    "Bảng → bảng markdown. Giữ nguyên số liệu, không suy diễn; "
    "đoạn không đọc được đánh dấu `[không đọc được]`. Không thêm lời dẫn."
)


class HybridExtractionError(RuntimeError):
    """The whole PDF yielded no text (every page empty or failed)."""


@dataclass
class HybridPage:
    page_no: int
    text: str
    method: str  # "text_layer" | "ocr" | "failed"


@dataclass
class HybridPagesResult:
    pages: list[HybridPage]
    pages_text: int = 0
    pages_ocr: int = 0
    pages_failed: int = 0

    def to_page_tuples(self) -> list[tuple[int, str]]:
        """Adapt to the (page_no, text) shape pages_to_marked_text expects."""
        return [(p.page_no, p.text) for p in self.pages]


def _extract_text_layers(content: bytes) -> list[str]:
    """Raw pdfplumber text layer per page (may be '' for scanned pages)."""
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def render_page_png(content: bytes, page_no: int) -> bytes:
    """Render one PDF page (1-indexed) to PNG bytes at ~200 DPI."""
    import pymupdf  # lazy: text-layer-only documents never need the renderer

    with pymupdf.open(stream=content, filetype="pdf") as doc:
        page = doc[page_no - 1]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(RENDER_ZOOM, RENDER_ZOOM))
        return pix.tobytes("png")


def extract_pages_hybrid(
    content: bytes,
    ocr: Callable[[bytes], str],
    render: Callable[[bytes, int], bytes] = render_page_png,
) -> HybridPagesResult:
    """Per-page hybrid extraction: text layer when long enough, OCR otherwise.

    A page whose OCR call raises InferenceError is recorded as method="failed"
    and the remaining pages continue (graceful degradation). If the document
    ends up with no text at all, raise so the caller does NOT mark it ingested
    (a content-hash skip would otherwise hide the failure forever).
    """
    result = HybridPagesResult(pages=[])
    for page_no, layer_text in enumerate(_extract_text_layers(content), start=1):
        body = layer_text.strip()
        if len(body) >= TEXT_LAYER_MIN_CHARS:
            result.pages.append(HybridPage(page_no, body, "text_layer"))
            result.pages_text += 1
            continue
        try:
            text = ocr(render(content, page_no)).strip()
        except InferenceError as exc:
            logger.warning("OCR failed for page %d: %r", page_no, exc)
            result.pages.append(HybridPage(page_no, "", "failed"))
            result.pages_failed += 1
            continue
        result.pages.append(HybridPage(page_no, text, "ocr"))
        result.pages_ocr += 1

    if all(not p.text.strip() for p in result.pages):
        raise HybridExtractionError(
            "PDF produced no text at all (pages text/ocr/failed="
            f"{result.pages_text}/{result.pages_ocr}/{result.pages_failed})"
        )
    logger.info(
        "Hybrid extract: %d pages (text=%d ocr=%d failed=%d)",
        len(result.pages), result.pages_text, result.pages_ocr, result.pages_failed,
    )
    return result


def build_gateway_ocr(gateway=None) -> Callable[[bytes], str]:
    """Default OCR callable: one Gemini vision call per page PNG via the gateway."""
    from services.inference.factory import build_default_gateway

    gw = gateway if gateway is not None else build_default_gateway()

    def _ocr(png_bytes: bytes) -> str:
        result = gw.run(InferenceRequest(
            agent_name="knowledge_ocr",
            task_type="page_ocr",
            system_prompt=OCR_SYSTEM_PROMPT,
            user_prompt=OCR_USER_PROMPT,
            output_mode="free_text",
            temperature=0.0,
            media=[("image/png", png_bytes)],
        ))
        return result.content

    return _ocr
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_pdf_ocr.py -q`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```powershell
git add ingestion\knowledge\pdf_ocr.py tests\ingestion\knowledge\test_pdf_ocr.py
git commit -m "feat: add hybrid text-layer/OCR page extractor for knowledge PDFs"
```

---

### Task 3: Xử lý lỗi — trang fail đi tiếp, cả file rỗng thì raise

**Files:**
- Modify: `ingestion/knowledge/pdf_ocr.py` (đã có sẵn logic từ Task 2 — task này chỉ chốt bằng test)
- Test: `tests/ingestion/knowledge/test_pdf_ocr.py` (thêm vào cuối file)

- [ ] **Step 1: Viết test (kỳ vọng pass luôn vì Task 2 đã code phòng thủ — nếu fail thì sửa lại Task 2)**

```python
def test_failed_ocr_page_continues_with_other_pages(monkeypatch):
    _patch_layers(monkeypatch, ["", "", LONG])
    ocr = FakeOCR(exc_on={1})                 # call OCR thứ nhất (trang 1) fail

    result = extract_pages_hybrid(b"%PDF", ocr, render=_fake_render)

    assert [p.method for p in result.pages] == ["failed", "ocr", "text_layer"]
    assert result.pages_failed == 1 and result.pages_ocr == 1 and result.pages_text == 1
    assert result.pages[0].text == ""         # trang fail giữ chỗ bằng text rỗng


def test_document_with_no_text_at_all_raises(monkeypatch):
    _patch_layers(monkeypatch, ["", ""])
    ocr = FakeOCR(exc_on={1, 2})              # mọi trang OCR đều fail

    with pytest.raises(HybridExtractionError):
        extract_pages_hybrid(b"%PDF", ocr, render=_fake_render)


def test_document_where_ocr_returns_empty_everywhere_raises(monkeypatch):
    _patch_layers(monkeypatch, ["", ""])
    ocr = FakeOCR(text="")                    # OCR "thành công" nhưng không có chữ

    with pytest.raises(HybridExtractionError):
        extract_pages_hybrid(b"%PDF", ocr, render=_fake_render)
```

- [ ] **Step 2: Chạy test**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_pdf_ocr.py -q`
Expected: tất cả PASS (logic đã nằm trong Task 2 Step 3; nếu có test đỏ — sửa `extract_pages_hybrid` cho khớp hành vi mô tả ở docstring, KHÔNG sửa test).

- [ ] **Step 3: Commit**

```powershell
git add tests\ingestion\knowledge\test_pdf_ocr.py
git commit -m "test: lock per-page OCR failure and empty-document behavior"
```

---

### Task 4: `render_page_png` với PDF thật + `build_gateway_ocr` với gateway giả

**Files:**
- Test: `tests/ingestion/knowledge/test_pdf_ocr.py` (thêm vào cuối file)

- [ ] **Step 1: Viết test**

```python
# --- render thật (PyMuPDF) ------------------------------------------------------

def _one_page_pdf(text: str) -> bytes:
    # PDF 1 trang sinh inline — cùng convention với tests/.../test_pdf_pages.py.
    pytest.importorskip("reportlab")
    from io import BytesIO
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, text)
    c.showPage()
    c.save()
    return buf.getvalue()


def test_render_page_png_produces_png_bytes():
    pytest.importorskip("pymupdf")
    png = pdf_ocr.render_page_png(_one_page_pdf("Hello"), 1)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"    # PNG magic bytes


def test_extract_text_layers_reads_real_pdf():
    pages = pdf_ocr._extract_text_layers(_one_page_pdf("Hello Trang"))
    assert len(pages) == 1
    assert "Hello" in pages[0]


# --- OCR callable mặc định qua gateway -------------------------------------------

class FakeGateway:
    def __init__(self, content="OCR TEXT"):
        self.requests = []
        self._content = content

    def run(self, request):
        self.requests.append(request)
        return SimpleNamespace(content=self._content)


def test_build_gateway_ocr_sends_png_through_media():
    gw = FakeGateway()
    ocr = build_gateway_ocr(gateway=gw)

    text = ocr(b"\x89PNG-bytes")

    assert text == "OCR TEXT"
    req = gw.requests[0]
    assert req.agent_name == "knowledge_ocr"
    assert req.task_type == "page_ocr"
    assert req.output_mode == "free_text"
    assert req.temperature == 0.0
    assert req.media == [("image/png", b"\x89PNG-bytes")]
```

- [ ] **Step 2: Chạy test, xác nhận pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_pdf_ocr.py -q`
Expected: tất cả PASS (code đã viết ở Task 2; nếu `reportlab` chưa cài, 2 test render bị SKIP — chấp nhận được, chúng là smoke test).

- [ ] **Step 3: Commit**

```powershell
git add tests\ingestion\knowledge\test_pdf_ocr.py
git commit -m "test: cover real-PDF rendering and gateway OCR request shape"
```

---

### Task 5: Probe script thủ công `scripts/ocr_probe.py`

**Files:**
- Create: `scripts/ocr_probe.py`

Theo convention `scripts/` của repo: driver một-lần, KHÔNG nằm trong test suite
(`testpaths` giới hạn ở `tests/`). Dùng để eyeball chất lượng OCR trên 1–2 file thật
(spec mục 9.6).

- [ ] **Step 1: Viết script**

Tạo `scripts/ocr_probe.py`:

```python
"""One-off probe: run the hybrid extractor on a real PDF and print the markdown.

Usage (cần GEMINI_API_KEY / GEMINI_API_KEYS export sẵn trong shell — repo không
dùng dotenv loader):

    .\\.venv\\Scripts\\python.exe scripts\\ocr_probe.py path\\to\\file.pdf --max-pages 3

NOT part of the test suite. OCR runs for EVERY image page of the file; --max-pages
only limits how many pages get printed.
"""
import argparse
import logging
from pathlib import Path

from ingestion.knowledge.pdf_ocr import build_gateway_ocr, extract_pages_hybrid


def main() -> int:
    parser = argparse.ArgumentParser(description="Eyeball OCR quality on one PDF")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--max-pages", type=int, default=3,
                        help="print only the first N pages (default 3)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = extract_pages_hybrid(args.pdf.read_bytes(), build_gateway_ocr())

    print(f"pages: text={result.pages_text} ocr={result.pages_ocr} "
          f"failed={result.pages_failed}")
    for page in result.pages[: args.max_pages]:
        print(f"\n===== [Trang {page.page_no}] method={page.method} =====")
        print(page.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke check cú pháp (không cần key, không cần PDF)**

Run: `.\.venv\Scripts\python.exe scripts\ocr_probe.py --help`
Expected: in usage, exit 0.

- [ ] **Step 3: (Tùy chọn, cần key + 1 PDF scan thật) chạy probe**

Run: `.\.venv\Scripts\python.exe scripts\ocr_probe.py <đường-dẫn-pdf-scan> --max-pages 2`
Expected: in thống kê trang + markdown để eyeball (bảng phải ra dạng `| ... |`).

- [ ] **Step 4: Commit**

```powershell
git add scripts\ocr_probe.py
git commit -m "chore: add manual OCR quality probe script"
```

---

## Định nghĩa hoàn thành (Plan 02)

- `extract_pages_hybrid`: text layer ≥ 50 ký tự → không call OCR; trang ảnh → render + OCR;
  1 trang fail → đi tiếp; cả file rỗng → `HybridExtractionError`.
- `build_gateway_ocr()` tạo đúng `InferenceRequest` (agent `knowledge_ocr`, media PNG).
- `pymupdf` được pin trong `requirements.txt`.
- `.\.venv\Scripts\python.exe -m pytest tests\ingestion\knowledge\test_pdf_ocr.py -q` xanh toàn bộ.
