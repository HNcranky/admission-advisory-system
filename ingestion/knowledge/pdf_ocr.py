"""Hybrid per-page text extraction for knowledge PDFs (text layer + Gemini OCR).

Pages whose pdfplumber text layer is long enough are used as-is; image-only
pages are rendered to PNG (PyMuPDF, ~200 DPI) and OCR'd through the inference
gateway. See docs/superpowers/specs/2026-06-04-scanned-pdf-knowledge-ocr-design.md.
"""
import io
import logging
from collections import Counter
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

# Guard chống repetition loop: bảng merged-cell có thể khiến model kẹt sinh dấu
# '-' vô hạn (1 trang NEU từng trả về ~1M ký tự '-'). Một trang giấy thật không
# thể vượt OCR_PAGE_MAX_CHARS; output mà một ký tự chiếm áp đảo cũng là rác.
OCR_PAGE_MAX_CHARS = 20_000
OCR_DOMINANT_CHAR_RATIO = 0.8
OCR_DOMINANT_MIN_CHARS = 2_000
# Retry với nhiệt độ > 0 để decode có nhiễu, thoát khỏi vòng lặp greedy.
OCR_RETRY_TEMPERATURE = 0.3


def is_degenerate_ocr(text: str) -> bool:
    """True nếu output OCR là sản phẩm của repetition loop, không phải nội dung trang."""
    if len(text) > OCR_PAGE_MAX_CHARS:
        return True
    compact = "".join(text.split())
    if len(compact) >= OCR_DOMINANT_MIN_CHARS:
        dominant = Counter(compact).most_common(1)[0][1]
        if dominant / len(compact) > OCR_DOMINANT_CHAR_RATIO:
            return True
    return False


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
        for temperature in (0.0, OCR_RETRY_TEMPERATURE):
            result = gw.run(InferenceRequest(
                agent_name="knowledge_ocr",
                task_type="page_ocr",
                system_prompt=OCR_SYSTEM_PROMPT,
                user_prompt=OCR_USER_PROMPT,
                output_mode="free_text",
                temperature=temperature,
                media=[("image/png", png_bytes)],
            ))
            text = result.content
            if not is_degenerate_ocr(text):
                return text
            logger.warning(
                "Degenerate OCR output (%d chars) at temperature %.1f%s",
                len(text), temperature,
                ", retrying" if temperature == 0.0 else "",
            )
        # Cả 2 lần đều rác → để extract_pages_hybrid đánh dấu trang failed
        # (các trang còn lại của tài liệu vẫn được ingest bình thường).
        raise InferenceError("OCR output degenerate after retry (repetition loop)")

    return _ocr
