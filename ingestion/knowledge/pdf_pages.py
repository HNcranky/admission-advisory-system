import io
import logging

import pdfplumber

logger = logging.getLogger(__name__)


def extract_pages(content: bytes) -> list[tuple[int, str]]:
    """Extract per-page text from a PDF as [(page_no, text), ...] (1-indexed)."""
    pages: list[tuple[int, str]] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages.append((i, text))
    logger.info("Extracted %d PDF pages", len(pages))
    return pages


def pages_to_marked_text(pages: list[tuple[int, str]]) -> str:
    """Join pages into one string, each non-empty page prefixed by `[Trang N]`
    and separated by a blank line so the chunker treats pages as blocks."""
    blocks: list[str] = []
    for page_no, text in pages:
        body = (text or "").strip()
        if not body:
            continue
        blocks.append(f"[Trang {page_no}]\n{body}")
    return "\n\n".join(blocks)
