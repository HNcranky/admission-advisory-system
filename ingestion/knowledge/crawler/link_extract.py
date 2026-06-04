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
