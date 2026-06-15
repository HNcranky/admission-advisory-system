import io
import logging

import pdfplumber

logger = logging.getLogger(__name__)


def _rows_to_markdown(rows: list[list]) -> str:
    """Convert a list of rows (from pdfplumber table.extract()) to a GFM markdown table."""
    cleaned = [
        [str(cell).strip().replace("|", "\\|") if cell is not None else ""
         for cell in row]
        for row in rows
        if any(cell for cell in row)
    ]
    if not cleaned:
        return ""
    max_cols = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (max_cols - len(r)) for r in cleaned]
    sep = "| " + " | ".join(["---"] * max_cols) + " |"
    lines = ["| " + " | ".join(cleaned[0]) + " |", sep]
    for row in cleaned[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _page_to_text(page) -> str:
    """Extract text from a pdfplumber page, converting detected tables to markdown."""
    tables = page.find_tables()
    if not tables:
        return page.extract_text() or ""

    # Sort tables top-to-bottom
    tables = sorted(tables, key=lambda t: t.bbox[1])
    parts: list[str] = []
    prev_bottom = 0

    for table in tables:
        x0, top, x1, bottom = table.bbox
        if top > prev_bottom:
            region = page.crop((0, prev_bottom, page.width, top))
            txt = region.extract_text() or ""
            if txt.strip():
                parts.append(txt.strip())
        md = _rows_to_markdown(table.extract())
        if md:
            parts.append(md)
        prev_bottom = bottom

    if prev_bottom < page.height:
        region = page.crop((0, prev_bottom, page.width, page.height))
        txt = region.extract_text() or ""
        if txt.strip():
            parts.append(txt.strip())

    return "\n\n".join(parts)


def extract_pages(content: bytes) -> list[tuple[int, str]]:
    """Extract per-page text from a PDF as [(page_no, text), ...] (1-indexed).
    HTML tables detected by pdfplumber are rendered as markdown tables."""
    pages: list[tuple[int, str]] = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = _page_to_text(page)
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
