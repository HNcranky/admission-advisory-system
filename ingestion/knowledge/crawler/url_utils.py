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
