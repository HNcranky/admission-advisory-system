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
