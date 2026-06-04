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
