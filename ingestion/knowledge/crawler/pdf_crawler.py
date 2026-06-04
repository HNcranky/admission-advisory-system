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
