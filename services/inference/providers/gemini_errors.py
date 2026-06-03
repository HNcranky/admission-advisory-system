"""Classify google-genai exceptions for key rotation.

google.genai.errors.APIError (and ClientError/ServerError) carry an int `code`
HTTP status. We treat 429 (quota), 401/403 (auth) and 5xx (server) as
"key-specific" — worth retrying on a different key. Anything else (e.g. a plain
network failure or a 4xx input error) is not helped by switching keys.
"""

import re

ROTATABLE_STATUSES = frozenset({401, 403, 429})

_STATUS_RE = re.compile(r"\b([1-5]\d{2})\b")
# 'retryDelay': '26s'  /  retryDelay=26s
_RETRY_DELAY_RE = re.compile(
    r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)\s*s", re.IGNORECASE
)
# "Please retry in 26.7s"
_RETRY_IN_RE = re.compile(r"retry in\s+(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


def extract_status_code(exc) -> int | None:
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    match = _STATUS_RE.search(str(exc))
    return int(match.group(1)) if match else None


def is_rotatable_error(exc) -> bool:
    status = extract_status_code(exc)
    if status is None:
        return False
    return status in ROTATABLE_STATUSES or 500 <= status < 600


def parse_retry_delay(exc) -> float | None:
    text = str(exc)
    for pattern in (_RETRY_DELAY_RE, _RETRY_IN_RE):
        match = pattern.search(text)
        if match:
            return float(match.group(1))
    return None
