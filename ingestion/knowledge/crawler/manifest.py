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
