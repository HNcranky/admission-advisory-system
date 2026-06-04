"""Extract <a> links and parse sitemaps for the focused crawler."""
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_SKIP_PREFIXES = ("#", "mailto:", "javascript:", "tel:")


def _decode(content: bytes | str) -> str:
    if isinstance(content, str):
        return content
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")


def extract_links(content: bytes | str, base_url: str) -> list[tuple[str, str]]:
    """Return [(absolute_url, anchor_text)] for usable <a href> links."""
    soup = BeautifulSoup(_decode(content), "html.parser")
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(_SKIP_PREFIXES):
            continue
        out.append((urljoin(base_url, href), a.get_text(" ", strip=True)))
    return out


import logging
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


def parse_sitemap_locs(xml_bytes: bytes) -> list[str]:
    """Return every <loc> value from a urlset OR sitemapindex (namespace-agnostic).
    Caller decides which locs are nested sitemaps (.xml) vs content URLs."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        logger.warning("sitemap parse failed: %r", exc)
        return []
    locs: list[str] = []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]  # strip namespace
        if tag == "loc" and el.text:
            locs.append(el.text.strip())
    return locs
