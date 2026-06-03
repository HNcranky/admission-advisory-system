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
