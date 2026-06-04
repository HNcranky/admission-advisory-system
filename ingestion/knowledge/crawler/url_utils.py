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
