"""robots.txt gate for the focused crawler (spec §6 politeness)."""
import logging
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from ingestion.fetchers.http_fetcher import http_fetch

logger = logging.getLogger(__name__)


def _load_robots(url: str, fetch):
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        body = fetch(robots_url).raw_content.decode("utf-8", errors="replace")
    except Exception as exc:  # missing/blocked robots.txt => no restrictions
        logger.info("no robots.txt at %s: %r", robots_url, exc)
        return None
    rp = RobotFileParser()
    rp.parse(body.splitlines())
    return rp


def build_robots_checker(*, fetch=http_fetch, user_agent: str = "*",
                         respect: bool = True):
    """Return allowed(url)->bool. respect=False => always allow.
    robots.txt is fetched + parsed once per host and cached."""
    if not respect:
        return lambda url: True

    cache: dict[str, RobotFileParser | None] = {}

    def allowed(url: str) -> bool:
        host = urlsplit(url).netloc.lower()
        if host not in cache:
            cache[host] = _load_robots(url, fetch)
        rp = cache[host]
        return True if rp is None else rp.can_fetch(user_agent, url)

    return allowed
