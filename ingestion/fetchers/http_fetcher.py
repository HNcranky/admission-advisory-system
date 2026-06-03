import time
import random
import hashlib
import logging
import requests
from datetime import datetime
from typing import Optional

from ingestion.config.settings import (
    FETCH_TIMEOUT, FETCH_MAX_RETRIES, FETCH_RETRY_BACKOFF, USER_AGENTS,
    FETCH_VERIFY_SSL,
)
from ingestion.models.pipeline_models import FetchResult

logger = logging.getLogger(__name__)


def _get_random_ua() -> str:
    return random.choice(USER_AGENTS)


def http_fetch(
    url: str,
    timeout: int = FETCH_TIMEOUT,
    max_retries: int = FETCH_MAX_RETRIES,
    verify_ssl: bool = FETCH_VERIFY_SSL,
) -> FetchResult:
    """
    Fetch a URL via HTTP with retry logic and full metadata.

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds
        max_retries: Maximum number of retry attempts
        verify_ssl: Whether to verify SSL certificates

    Returns:
        FetchResult with full metadata

    Raises:
        requests.HTTPError: If all retries exhausted
    """
    headers = {
        "User-Agent": _get_random_ua(),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
    }

    if not verify_ssl:
        logger.warning(
            "SSL verification is disabled for %s. "
            "Set ADVISORY_FETCH_VERIFY_SSL=true to enforce it.",
            url,
        )

    last_exception = None

    for attempt in range(max_retries):
        try:
            start_time = time.time()

            response = requests.get(
                url,
                headers=headers,
                timeout=timeout,
                verify=verify_ssl,
                allow_redirects=True,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            response.raise_for_status()

            raw_content = response.content
            content_hash = hashlib.sha256(raw_content).hexdigest()

                                                     
            resp_headers = dict(response.headers)

            result = FetchResult(
                url=url,
                final_url=str(response.url),
                raw_content=raw_content,
                content_type=response.headers.get("Content-Type", ""),
                http_status=response.status_code,
                headers=resp_headers,
                fetched_at=datetime.now(),
                content_hash=content_hash,
                fetch_strategy_used="http",
                fetch_duration_ms=elapsed_ms,
            )

            logger.info(
                f"Fetched {url} → {result.http_status} "
                f"({len(raw_content)} bytes, {elapsed_ms}ms)"
            )

            return result

        except requests.RequestException as e:
            last_exception = e
            wait_time = FETCH_RETRY_BACKOFF * (2 ** attempt)
            logger.warning(
                f"Fetch attempt {attempt + 1}/{max_retries} failed for {url}: "
                f"{e}. Retrying in {wait_time:.1f}s..."
            )
            if attempt < max_retries - 1:
                time.sleep(wait_time)

                           
    logger.error(f"All {max_retries} fetch attempts failed for {url}")
    raise last_exception  # type: ignore