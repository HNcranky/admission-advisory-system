import logging
from typing import List, Dict
from bs4 import BeautifulSoup, NavigableString, Tag

from ingestion.models.pipeline_models import ParsedContent, DocumentType

logger = logging.getLogger(__name__)


class ContentSelectorNotFound(Exception):
    """Raised when a caller-supplied CSS selector matches no element."""

    def __init__(self, selector: str, url: str = ""):
        self.selector = selector
        self.url = url
        super().__init__(
            f"CSS selector {selector!r} matched no element on {url or '<html>'}"
        )


def parse_html(content: bytes, url: str = "", selector: str | None = None) -> ParsedContent:
    """
    Parse HTML content into structured ParsedContent.

    Args:
        content: Raw HTML bytes
        url: Source URL (for logging)

    Returns:
        ParsedContent with text, headings, tables, links
    """
                     
    try:
        html_str = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            html_str = content.decode("latin-1")
        except UnicodeDecodeError:
            html_str = content.decode("utf-8", errors="replace")

    soup = BeautifulSoup(html_str, "html.parser")

                                               
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()

                                                                  
    title = None
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True)

                                                                  
    if selector is not None:
        content_tag = soup.select_one(selector)
        if content_tag is None:
            raise ContentSelectorNotFound(selector, url)
    else:
        content_tag = _find_content_area(soup)

                                                                  
    headings = _extract_headings(content_tag)

                                                                  
    tables = _extract_tables(content_tag)

                                                                  
    links = _extract_links(content_tag)

                                                                  
    images = _extract_images(content_tag)

    # Replace each <table> with its markdown equivalent so the text field
    # preserves tabular structure for RAG (same intent as PDF OCR's "Bảng → bảng markdown").
    for table in content_tag.find_all("table"):
        md = _table_to_markdown(table)
        table.replace_with(NavigableString(f"\n\n{md}\n\n") if md else "")

    text = content_tag.get_text(separator="\n", strip=True)

    parsed = ParsedContent(
        text=text,
        title=title,
        headings=headings,
        tables=tables,
        links=links,
        images=images,
        document_type=DocumentType.HTML_ARTICLE,
        parser_used="html_parser",
    )

    logger.info(
        f"Parsed HTML: {len(text)} chars, "
        f"{len(headings)} headings, "
        f"{len(tables)} tables, "
        f"{len(links)} links"
    )

    return parsed


def _find_content_area(soup: BeautifulSoup) -> Tag:
    """Find the main content area, falling back through several strategies."""
                                                           
    selectors = [
        ("article", {}),
        ("div", {"class": "content"}),
        ("div", {"class": "post-content"}),
        ("div", {"class": "entry-content"}),
        ("div", {"class": "article-content"}),
        ("main", {}),
        ("div", {"id": "content"}),
        ("div", {"role": "main"}),
    ]

    for tag_name, attrs in selectors:
        found = soup.find(tag_name, attrs)
        if found:
            return found

                    
    return soup.body or soup


def _table_to_markdown(table: Tag) -> str:
    """Convert an HTML <table> to a GitHub-flavoured markdown table string."""
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = [
            td.get_text(" ", strip=True).replace("|", "\\|")
            for td in tr.find_all(["td", "th"])
        ]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    max_cols = max(len(r) for r in rows)
    rows = [r + [""] * (max_cols - len(r)) for r in rows]
    sep = "| " + " | ".join(["---"] * max_cols) + " |"
    lines = ["| " + " | ".join(rows[0]) + " |", sep]
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _extract_headings(tag: Tag) -> List[str]:
    """Extract all heading text from h1-h6."""
    headings = []
    for h in tag.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        text = h.get_text(strip=True)
        if text:
            headings.append(f"[{h.name}] {text}")
    return headings


def _extract_tables(tag: Tag) -> List[List[List[str]]]:
    """Extract tables as list of rows, each row is list of cell texts."""
    tables = []
    for table in tag.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = []
            for td in tr.find_all(["td", "th"]):
                cells.append(td.get_text(strip=True))
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def _extract_links(tag: Tag) -> List[Dict[str, str]]:
    """Extract all links with their text."""
    links = []
    seen_urls = set()
    for a in tag.find_all("a", href=True):
        url = a["href"]
        text = a.get_text(strip=True)
        if url and url not in seen_urls and not url.startswith("javascript:"):
            links.append({"url": url, "text": text})
            seen_urls.add(url)
    return links


def _extract_images(tag: Tag) -> List[str]:
    """Extract image URLs."""
    images = []
    for img in tag.find_all("img", src=True):
        images.append(img["src"])
    return images