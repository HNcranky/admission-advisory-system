"""Review manifest for crawled PDFs: persist, merge, tag, mark-ingested.

status lifecycle: pending -> (human) keep|skip -> (ingest) done
"""
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from ingestion.knowledge.crawler.pdf_crawler import CandidatePdf

# Relevance hint only — NEVER a filter. Every PDF is listed (D4).
RELEVANCE_KEYWORDS = (
    "tuyển sinh", "tuyen sinh", "đề án", "de an", "chỉ tiêu", "chi tieu",
    "thông báo", "thong bao", "phương thức", "phuong thuc",
    "học phí", "hoc phi", "học bổng", "hoc bong",
)


@dataclass
class ManifestEntry:
    school: str
    url: str
    anchor_text: str = ""
    found_on: str = ""
    content_type: str | None = None
    size_bytes: int | None = None
    last_modified: str | None = None
    discovered_at: str = ""
    relevance: str = "low"
    status: str = "pending"
    already_ingested: bool = False


def load_manifest(path) -> list[ManifestEntry]:
    p = Path(path)
    if not p.exists():
        return []
    return [ManifestEntry(**e) for e in json.loads(p.read_text(encoding="utf-8"))]


def save_manifest(path, entries: list[ManifestEntry]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def tag_relevance(anchor_text: str, url: str) -> str:
    # Normalize URL separators (slug hyphens, path slashes) to spaces so
    # keywords like "tuyen sinh" match URL slugs like ".../tuyen-sinh/...".
    haystack = f"{anchor_text} {url}".lower().translate(str.maketrans("-_/.", "    "))
    return "high" if any(k in haystack for k in RELEVANCE_KEYWORDS) else "low"


def merge_candidates(existing: list[ManifestEntry], candidates: list[CandidatePdf],
                     *, discovered_at: str) -> list[ManifestEntry]:
    """Keep existing entries (and their human decisions); refresh metadata on
    rediscovery; append never-seen URLs as status='pending'. This is the
    anti-miss guarantee (D2): a re-crawl only ever ADDS pending work."""
    by_url: dict[str, ManifestEntry] = {e.url: e for e in existing}
    for c in candidates:
        if c.url in by_url:
            e = by_url[c.url]
            e.anchor_text = e.anchor_text or c.anchor_text
            e.content_type = c.content_type or e.content_type
            if c.size_bytes is not None:
                e.size_bytes = c.size_bytes
            e.last_modified = c.last_modified or e.last_modified
            continue
        by_url[c.url] = ManifestEntry(
            school=c.school, url=c.url, anchor_text=c.anchor_text,
            found_on=c.found_on, content_type=c.content_type,
            size_bytes=c.size_bytes, last_modified=c.last_modified,
            discovered_at=discovered_at,
            relevance=tag_relevance(c.anchor_text, c.url),
            status="pending", already_ingested=False,
        )
    return list(by_url.values())


def mark_already_ingested(entries: list[ManifestEntry], doc_repo) -> list[ManifestEntry]:
    """Set already_ingested by checking the knowledge_documents store by URL."""
    for e in entries:
        e.already_ingested = doc_repo.get_document_by_url(e.url) is not None
    return entries
