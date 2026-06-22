import logging
import re
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

    # Render the content tree to structured markdown so the text field keeps the
    # source's heading/section/list/table shape (instead of a flat newline dump).
    # Blank lines between blocks double as chunk boundaries for the RAG chunker.
    text = _to_markdown(content_tag)

    content_label = _extract_content_label(soup, title, url)

    parsed = ParsedContent(
        text=text,
        title=title,
        content_label=content_label,
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


_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# Tags whose text is layout noise, not content.
_SKIP_BLOCKS = {"br", "hr", "img", "figure", "svg", "button", "input", "nav"}
_WS = re.compile(r"\s+")


def _inline_md(tag: Tag) -> str:
    """Render an element's inline content to markdown (bold/italic preserved).

    Whitespace is collapsed to single spaces. Nested block tags are flattened
    into the line — callers only pass leaf blocks (headings, p, li)."""
    parts: list[str] = []
    for node in tag.children:
        if isinstance(node, NavigableString):
            parts.append(str(node))
            continue
        name = node.name
        inner = _inline_md(node)
        if not inner.strip():
            continue
        if name in ("strong", "b"):
            parts.append(f"**{inner.strip()}**")
        elif name in ("em", "i"):
            parts.append(f"*{inner.strip()}*")
        else:  # a, span, and anything else: keep the text inline
            parts.append(inner)
    return _WS.sub(" ", "".join(parts)).strip()


def _render_blocks(tag: Tag) -> list[str]:
    """Walk a content tree depth-first, emitting one markdown block per element."""
    blocks: list[str] = []
    for child in tag.children:
        if isinstance(child, NavigableString):
            text = _WS.sub(" ", str(child)).strip()
            if text:
                blocks.append(text)
            continue

        name = child.name
        if name in _SKIP_BLOCKS:
            continue
        if name in _HEADINGS:
            text = _inline_md(child)
            if text:
                blocks.append("#" * int(name[1]) + " " + text)
        elif name == "p":
            text = _inline_md(child)
            if text:
                blocks.append(text)
        elif name in ("ul", "ol"):
            items = [
                "- " + _inline_md(li)
                for li in child.find_all("li", recursive=False)
                if _inline_md(li)
            ]
            if items:
                blocks.append("\n".join(items))
        elif name == "table":
            md = _table_to_markdown(child)
            if md:
                blocks.append(md)
        else:  # container (div, section, article, ...): recurse
            blocks.extend(_render_blocks(child))
    return blocks


def _to_markdown(tag: Tag) -> str:
    """Structured-markdown text for a content region; blank-line separated blocks."""
    return "\n\n".join(b for b in _render_blocks(tag) if b.strip())


def _extract_content_label(
    soup: BeautifulSoup, title: str | None, url: str
) -> str | None:
    """Clean page label: breadcrumb-active → <title> → de-slugified URL tail."""
    active = soup.select_one("li.breadcrumb-item.active")
    if active:
        text = active.get_text(" ", strip=True)
        if text:
            return text
    if title:
        return title
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    if slug:
        return slug.replace("-", " ").strip() or None
    return None


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