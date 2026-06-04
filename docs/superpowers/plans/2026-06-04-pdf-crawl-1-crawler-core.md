# PDF Crawler Core Implementation Plan (1/4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the offline crawl "engine" — a per-school focused crawler that, from seed URLs, walks same-domain HTML (BFS, depth/page bounded) plus `sitemap.xml`, and returns a deduped list of candidate PDF URLs.

**Architecture:** New package `ingestion/knowledge/crawler/`. Pure-logic units (URL normalize/scope, link extraction, sitemap parsing) with no network, plus a `crawl_target()` orchestrator that takes injectable `fetch`/`head` callables so the whole BFS is testable offline. No DB, no LLM — this plan only discovers URLs.

**Tech Stack:** Python 3.12, Pydantic v2, BeautifulSoup (`bs4`, already a dep via `parsers/html_parser.py`), stdlib `urllib.parse` + `xml.etree`, `requests` (via existing `http_fetch`).

This is plan **1 of 4**. It produces `crawl_target(target) -> list[CandidatePdf]`, consumed by plan 2 (manifest + `crawl` CLI).

---

### Task 1: Crawl target config model + seed file

**Files:**
- Create: `ingestion/knowledge/crawler/__init__.py` (empty)
- Create: `ingestion/knowledge/crawler/config.py`
- Create: `ingestion/knowledge/crawler/seeds/crawler_targets.json`
- Test: `tests/ingestion/knowledge/test_crawl_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ingestion/knowledge/test_crawl_config.py
import pytest
from pydantic import ValidationError

from ingestion.knowledge.crawler.config import CrawlTarget, load_targets


def test_load_targets_parses_seed():
    targets = load_targets()
    assert {t.school for t in targets} == {"HUST", "NEU", "VNU-UET"}
    hust = next(t for t in targets if t.school == "HUST")
    assert hust.seeds and all(s.startswith("http") for s in hust.seeds)
    assert hust.max_depth >= 1 and hust.max_pages >= 1


def test_unknown_school_rejected():
    with pytest.raises(ValidationError):
        CrawlTarget(school="FOO", seeds=["https://x"], allow_domains=["x"])


def test_defaults_applied():
    t = CrawlTarget(school="HUST", seeds=["https://hust.edu.vn"], allow_domains=["hust.edu.vn"])
    assert t.allow_path_prefixes == []
    assert t.max_depth == 2 and t.max_pages == 300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.knowledge.crawler'`

- [ ] **Step 3: Create the package and config module**

```python
# ingestion/knowledge/crawler/__init__.py
```
(empty file)

```python
# ingestion/knowledge/crawler/config.py
"""Per-school crawl targets for the focused PDF crawler."""
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from ingestion.knowledge.local_metadata import KNOWN_SCHOOLS

_DEFAULT_SEED = Path(__file__).parent / "seeds" / "crawler_targets.json"


class CrawlTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    school: str
    seeds: list[str]
    allow_domains: list[str]
    allow_path_prefixes: list[str] = []
    max_depth: int = 2
    max_pages: int = 300

    @field_validator("school")
    @classmethod
    def _school_known(cls, v: str) -> str:
        if v not in KNOWN_SCHOOLS:
            raise ValueError(f"school {v!r} not in KNOWN_SCHOOLS {KNOWN_SCHOOLS}")
        return v


def load_targets(path: Path | None = None) -> list[CrawlTarget]:
    p = path or _DEFAULT_SEED
    raw = json.loads(Path(p).read_text(encoding="utf-8"))
    return [CrawlTarget(**entry) for entry in raw]
```

```json
// ingestion/knowledge/crawler/seeds/crawler_targets.json
[
  {"school": "HUST",
   "seeds": ["https://www.hust.edu.vn/tuyen-sinh.htm"],
   "allow_domains": ["hust.edu.vn"],
   "allow_path_prefixes": ["/tuyen-sinh", "/uploads"],
   "max_depth": 2, "max_pages": 300},
  {"school": "NEU",
   "seeds": ["https://tuyensinh.neu.edu.vn/"],
   "allow_domains": ["neu.edu.vn"],
   "allow_path_prefixes": [],
   "max_depth": 2, "max_pages": 300},
  {"school": "VNU-UET",
   "seeds": ["https://uet.vnu.edu.vn/"],
   "allow_domains": ["uet.vnu.edu.vn"],
   "allow_path_prefixes": [],
   "max_depth": 2, "max_pages": 300}
]
```

Note: `crawler_targets.json` is committed config (unlike `data/knowledge/`, which is gitignored). Seed URLs are best-effort starting points; adjust per school after the first real crawl.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_config.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/crawler/__init__.py ingestion/knowledge/crawler/config.py ingestion/knowledge/crawler/seeds/crawler_targets.json tests/ingestion/knowledge/test_crawl_config.py
git commit -m "feat: add per-school crawl target config for PDF crawler"
```

---

### Task 2: URL normalization

**Files:**
- Create: `ingestion/knowledge/crawler/url_utils.py`
- Test: `tests/ingestion/knowledge/test_crawl_url_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ingestion/knowledge/test_crawl_url_utils.py
from ingestion.knowledge.crawler.url_utils import normalize_url


def test_strips_fragment():
    assert normalize_url("https://a.vn/p#sec") == "https://a.vn/p"


def test_strips_trailing_slash_but_keeps_root():
    assert normalize_url("https://a.vn/p/") == "https://a.vn/p"
    assert normalize_url("https://a.vn/") == "https://a.vn/"


def test_lowercases_scheme_and_host_keeps_path_case():
    assert normalize_url("HTTPS://A.VN/Path") == "https://a.vn/Path"


def test_keeps_query():
    assert normalize_url("https://a.vn/p?id=2") == "https://a.vn/p?id=2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_url_utils.py -q`
Expected: FAIL — `ModuleNotFoundError: ... url_utils`

- [ ] **Step 3: Implement normalize_url**

```python
# ingestion/knowledge/crawler/url_utils.py
"""URL normalization + scope filtering for the focused crawler."""
from urllib.parse import urlsplit, urlunsplit


def normalize_url(url: str) -> str:
    """Canonical form for dedup: lowercase scheme+host, drop fragment,
    drop trailing slash (except root). Query is preserved."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_url_utils.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/crawler/url_utils.py tests/ingestion/knowledge/test_crawl_url_utils.py
git commit -m "feat: add URL normalization for crawler dedup"
```

---

### Task 3: Scope filters + PDF detection

**Files:**
- Modify: `ingestion/knowledge/crawler/url_utils.py`
- Test: `tests/ingestion/knowledge/test_crawl_url_utils.py` (append)

- [ ] **Step 1: Write the failing test (append to the same test file)**

```python
# append to tests/ingestion/knowledge/test_crawl_url_utils.py
from ingestion.knowledge.crawler.url_utils import (
    host_allowed, path_allowed, is_pdf_url,
)


def test_host_allowed_matches_subdomains():
    assert host_allowed("https://ts.hust.edu.vn/x", ["hust.edu.vn"])
    assert host_allowed("https://hust.edu.vn/x", ["hust.edu.vn"])
    assert not host_allowed("https://evil.com/x", ["hust.edu.vn"])
    assert not host_allowed("https://nothust.edu.vn.evil.com/x", ["hust.edu.vn"])


def test_path_allowed_empty_prefixes_allows_all():
    assert path_allowed("https://a.vn/anything", [])


def test_path_allowed_prefix_match():
    assert path_allowed("https://a.vn/tuyen-sinh/x", ["/tuyen-sinh"])
    assert not path_allowed("https://a.vn/news/x", ["/tuyen-sinh"])


def test_is_pdf_url_by_extension_and_content_type():
    assert is_pdf_url("https://a.vn/de-an.pdf")
    assert is_pdf_url("https://a.vn/file", content_type="application/pdf")
    assert not is_pdf_url("https://a.vn/page.html")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_url_utils.py -q`
Expected: FAIL — `ImportError: cannot import name 'host_allowed'`

- [ ] **Step 3: Add the functions to url_utils.py**

```python
# append to ingestion/knowledge/crawler/url_utils.py


def host_allowed(url: str, allow_domains: list[str]) -> bool:
    host = urlsplit(url).netloc.lower().split(":")[0]
    return any(host == d or host.endswith("." + d) for d in allow_domains)


def path_allowed(url: str, allow_path_prefixes: list[str]) -> bool:
    if not allow_path_prefixes:
        return True
    path = urlsplit(url).path
    return any(path.startswith(p) for p in allow_path_prefixes)


def is_pdf_url(url: str, content_type: str | None = None) -> bool:
    if content_type and "pdf" in content_type.lower():
        return True
    return urlsplit(url).path.lower().endswith(".pdf")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_url_utils.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/crawler/url_utils.py tests/ingestion/knowledge/test_crawl_url_utils.py
git commit -m "feat: add host/path scope filters and PDF URL detection"
```

---

### Task 4: HTML link extraction

**Files:**
- Create: `ingestion/knowledge/crawler/link_extract.py`
- Test: `tests/ingestion/knowledge/test_crawl_link_extract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ingestion/knowledge/test_crawl_link_extract.py
from ingestion.knowledge.crawler.link_extract import extract_links

HTML = b"""
<html><body>
  <a href="/tuyen-sinh/de-an-2026.pdf">De an tuyen sinh 2026</a>
  <a href="https://hust.edu.vn/news/abc.htm">  Tin tuc  </a>
  <a href="#top">skip anchor</a>
  <a href="mailto:x@hust.edu.vn">skip mail</a>
  <a>no href</a>
</body></html>
"""


def test_extracts_absolute_urls_and_anchor_text():
    links = extract_links(HTML, "https://hust.edu.vn/tuyen-sinh.htm")
    urls = {u for u, _ in links}
    assert "https://hust.edu.vn/tuyen-sinh/de-an-2026.pdf" in urls
    assert "https://hust.edu.vn/news/abc.htm" in urls


def test_skips_fragment_mailto_and_missing_href():
    links = extract_links(HTML, "https://hust.edu.vn/tuyen-sinh.htm")
    urls = {u for u, _ in links}
    assert not any(u.startswith("mailto:") for u in urls)
    assert "https://hust.edu.vn/tuyen-sinh.htm#top" not in urls
    assert len(links) == 2


def test_anchor_text_is_stripped():
    links = dict(extract_links(HTML, "https://hust.edu.vn/tuyen-sinh.htm"))
    assert links["https://hust.edu.vn/news/abc.htm"] == "Tin tuc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_link_extract.py -q`
Expected: FAIL — `ModuleNotFoundError: ... link_extract`

- [ ] **Step 3: Implement extract_links**

```python
# ingestion/knowledge/crawler/link_extract.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_link_extract.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/crawler/link_extract.py tests/ingestion/knowledge/test_crawl_link_extract.py
git commit -m "feat: extract anchor links from crawled HTML pages"
```

---

### Task 5: Sitemap parsing

**Files:**
- Modify: `ingestion/knowledge/crawler/link_extract.py`
- Test: `tests/ingestion/knowledge/test_crawl_link_extract.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
# append to tests/ingestion/knowledge/test_crawl_link_extract.py
from ingestion.knowledge.crawler.link_extract import parse_sitemap_locs

URLSET = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://a.vn/de-an.pdf</loc></url>
  <url><loc>https://a.vn/page</loc></url>
</urlset>"""

SITEMAPINDEX = b"""<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://a.vn/sitemap-1.xml</loc></sitemap>
</sitemapindex>"""


def test_parse_urlset_returns_all_locs():
    assert parse_sitemap_locs(URLSET) == ["https://a.vn/de-an.pdf", "https://a.vn/page"]


def test_parse_sitemapindex_returns_nested_sitemap_locs():
    assert parse_sitemap_locs(SITEMAPINDEX) == ["https://a.vn/sitemap-1.xml"]


def test_parse_invalid_xml_returns_empty():
    assert parse_sitemap_locs(b"not xml at all") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_link_extract.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_sitemap_locs'`

- [ ] **Step 3: Add parse_sitemap_locs**

```python
# append to ingestion/knowledge/crawler/link_extract.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_link_extract.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/crawler/link_extract.py tests/ingestion/knowledge/test_crawl_link_extract.py
git commit -m "feat: parse sitemap urlset and sitemapindex locs"
```

---

### Task 6: HEAD metadata probe

**Files:**
- Create: `ingestion/knowledge/crawler/pdf_crawler.py`
- Test: `tests/ingestion/knowledge/test_crawl_head.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/ingestion/knowledge/test_crawl_head.py
from ingestion.knowledge.crawler.pdf_crawler import parse_head_headers


def test_parse_head_headers_extracts_fields():
    out = parse_head_headers({
        "Content-Type": "application/pdf",
        "Content-Length": "12345",
        "Last-Modified": "Mon, 01 Mar 2026 00:00:00 GMT",
    })
    assert out == {
        "content_type": "application/pdf",
        "size_bytes": 12345,
        "last_modified": "Mon, 01 Mar 2026 00:00:00 GMT",
    }


def test_parse_head_headers_handles_missing_and_bad_length():
    out = parse_head_headers({"Content-Length": "not-a-number"})
    assert out == {"content_type": None, "size_bytes": None, "last_modified": None}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_head.py -q`
Expected: FAIL — `ModuleNotFoundError: ... pdf_crawler`

- [ ] **Step 3: Create pdf_crawler.py with the header parser + fetch_head**

```python
# ingestion/knowledge/crawler/pdf_crawler.py
"""Focused per-school PDF crawler: BFS same-domain + sitemap, returns candidates."""
import logging
from collections import deque
from dataclasses import dataclass

import requests

from ingestion.config.settings import FETCH_TIMEOUT, FETCH_VERIFY_SSL
from ingestion.fetchers.http_fetcher import http_fetch
from ingestion.knowledge.crawler.config import CrawlTarget
from ingestion.knowledge.crawler.link_extract import extract_links, parse_sitemap_locs
from ingestion.knowledge.crawler.url_utils import (
    host_allowed, is_pdf_url, normalize_url, path_allowed,
)

logger = logging.getLogger(__name__)


@dataclass
class CandidatePdf:
    school: str
    url: str
    anchor_text: str
    found_on: str
    content_type: str | None = None
    size_bytes: int | None = None
    last_modified: str | None = None


def parse_head_headers(headers: dict) -> dict:
    """Extract {content_type, size_bytes, last_modified} from response headers."""
    raw_len = headers.get("Content-Length")
    try:
        size = int(raw_len) if raw_len is not None else None
    except (TypeError, ValueError):
        size = None
    return {
        "content_type": headers.get("Content-Type"),
        "size_bytes": size,
        "last_modified": headers.get("Last-Modified"),
    }


def fetch_head(url: str, verify_ssl: bool = FETCH_VERIFY_SSL) -> dict | None:
    """HEAD probe for PDF metadata. Returns None if HEAD is unsupported/failed."""
    try:
        resp = requests.head(url, allow_redirects=True, timeout=FETCH_TIMEOUT,
                             verify=verify_ssl)
        if resp.status_code >= 400:
            return None
        return parse_head_headers(dict(resp.headers))
    except requests.RequestException as exc:
        logger.warning("HEAD failed for %s: %r", url, exc)
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_head.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/crawler/pdf_crawler.py tests/ingestion/knowledge/test_crawl_head.py
git commit -m "feat: add HEAD metadata probe for PDF candidates"
```

---

### Task 7: BFS crawl_target orchestrator

**Files:**
- Modify: `ingestion/knowledge/crawler/pdf_crawler.py`
- Test: `tests/ingestion/knowledge/test_crawl_target.py`

- [ ] **Step 1: Write the failing test (fake site via injected fetch)**

```python
# tests/ingestion/knowledge/test_crawl_target.py
from ingestion.knowledge.crawler.config import CrawlTarget
from ingestion.knowledge.crawler.pdf_crawler import CandidatePdf, crawl_target


def _page(html: str):
    class FR:
        content_type = "text/html"
        raw_content = html.encode("utf-8")
    return FR()


# Fake site graph keyed by normalized URL.
SITE = {
    "https://a.vn/seed": _page(
        '<a href="/seed/de-an.pdf">De an</a>'
        '<a href="/seed/sub">Sub page</a>'
        '<a href="https://other.com/x.pdf">offsite pdf</a>'
    ),
    "https://a.vn/seed/sub": _page(
        '<a href="/seed/phu-luc.pdf">Phu luc</a>'
        '<a href="/seed/sub">self loop</a>'
    ),
}


def _fake_fetch(url):
    return SITE[url]


def _no_head(url, verify_ssl=True):
    return None


def test_crawl_collects_same_domain_pdfs_and_skips_offsite():
    target = CrawlTarget(school="HUST", seeds=["https://a.vn/seed"],
                         allow_domains=["a.vn"], max_depth=2, max_pages=50)
    pdfs = crawl_target(target, fetch=_fake_fetch, head=_no_head, sitemap=False)
    urls = {p.url for p in pdfs}
    assert urls == {"https://a.vn/seed/de-an.pdf", "https://a.vn/seed/phu-luc.pdf"}
    assert all(isinstance(p, CandidatePdf) and p.school == "HUST" for p in pdfs)


def test_depth_limit_blocks_deeper_pages():
    target = CrawlTarget(school="HUST", seeds=["https://a.vn/seed"],
                         allow_domains=["a.vn"], max_depth=0, max_pages=50)
    pdfs = crawl_target(target, fetch=_fake_fetch, head=_no_head, sitemap=False)
    # depth 0: only the seed page is read; its sub page is never crawled
    assert {p.url for p in pdfs} == {"https://a.vn/seed/de-an.pdf"}


def test_max_pages_caps_crawl():
    seen = []

    def counting_fetch(url):
        seen.append(url)
        return _fake_fetch(url)

    target = CrawlTarget(school="HUST", seeds=["https://a.vn/seed"],
                         allow_domains=["a.vn"], max_depth=5, max_pages=1)
    crawl_target(target, fetch=counting_fetch, head=_no_head, sitemap=False)
    assert len(seen) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_target.py -q`
Expected: FAIL — `ImportError: cannot import name 'crawl_target'`

- [ ] **Step 3: Implement crawl_target (and a sitemap expander)**

```python
# append to ingestion/knowledge/crawler/pdf_crawler.py


def _record_pdf(seen: dict, target: CrawlTarget, url: str, anchor: str,
                found_on: str, head) -> None:
    if url in seen or not host_allowed(url, target.allow_domains):
        return
    meta = head(url) or {}
    seen[url] = CandidatePdf(
        school=target.school, url=url, anchor_text=anchor, found_on=found_on,
        content_type=meta.get("content_type"), size_bytes=meta.get("size_bytes"),
        last_modified=meta.get("last_modified"),
    )


def _expand_sitemap(target: CrawlTarget, fetch, seen: dict, head) -> None:
    for domain in target.allow_domains:
        sm_url = f"https://{domain}/sitemap.xml"
        try:
            locs = parse_sitemap_locs(fetch(sm_url).raw_content)
        except Exception as exc:  # missing/blocked sitemap is non-fatal
            logger.info("no usable sitemap at %s: %r", sm_url, exc)
            continue
        for loc in locs:
            n = normalize_url(loc)
            if is_pdf_url(n):
                _record_pdf(seen, target, n, "", sm_url, head)


def crawl_target(target: CrawlTarget, *, fetch=http_fetch, head=fetch_head,
                 sitemap: bool = True) -> list[CandidatePdf]:
    """BFS same-domain from seeds (bounded by max_depth/max_pages), plus sitemap.
    Returns deduped CandidatePdf list. One bad page never aborts the crawl."""
    seen_pdfs: dict[str, CandidatePdf] = {}
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque(
        (normalize_url(s), 0) for s in target.seeds
    )
    pages_crawled = 0

    if sitemap:
        _expand_sitemap(target, fetch, seen_pdfs, head)

    while queue and pages_crawled < target.max_pages:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        try:
            fr = fetch(url)
        except Exception as exc:  # one bad page must not abort the crawl
            logger.warning("crawl fetch failed %s: %r", url, exc)
            continue
        pages_crawled += 1
        for raw_url, anchor in extract_links(fr.raw_content, url):
            n = normalize_url(raw_url)
            if is_pdf_url(n):
                _record_pdf(seen_pdfs, target, n, anchor, url, head)
            elif (depth < target.max_depth
                  and n not in visited
                  and host_allowed(n, target.allow_domains)
                  and path_allowed(n, target.allow_path_prefixes)):
                queue.append((n, depth + 1))

    logger.info("Crawl %s: %d pages, %d PDFs", target.school, pages_crawled,
                len(seen_pdfs))
    return list(seen_pdfs.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_target.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the whole crawler test group**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_crawl_config.py tests/ingestion/knowledge/test_crawl_url_utils.py tests/ingestion/knowledge/test_crawl_link_extract.py tests/ingestion/knowledge/test_crawl_head.py tests/ingestion/knowledge/test_crawl_target.py -q`
Expected: PASS (all green)

- [ ] **Step 6: Commit**

```bash
git add ingestion/knowledge/crawler/pdf_crawler.py tests/ingestion/knowledge/test_crawl_target.py
git commit -m "feat: BFS focused crawler returning candidate PDFs"
```

---

## Done when
- `crawl_target(target)` returns a deduped `list[CandidatePdf]` for a `CrawlTarget`, bounded by `max_depth`/`max_pages`, same-domain only, including sitemap-sourced PDFs.
- All crawler unit tests pass offline (no network, injected `fetch`/`head`).
- Next: plan 2 wires this into manifest persistence + the `crawl` CLI.
