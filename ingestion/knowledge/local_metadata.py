"""Metadata resolution for locally-dropped knowledge PDFs.

Priority per NEW file: overrides.json -> LLM classify {school, year} from the
first pages' text -> year regex from the filename -> school="unknown" + WARNING
(the file is still ingested; the user adds an override and re-runs).
See docs/superpowers/specs/2026-06-04-scanned-pdf-knowledge-ocr-design.md (5.3).
"""
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from services.inference.models import InferenceError, InferenceRequest

logger = logging.getLogger(__name__)

# Hard filter in vector_search — MUST stay in sync with the school codes used in
# knowledge_sources.json and the intent router. Anything else maps to "unknown".
KNOWN_SCHOOLS = ("HUST", "NEU", "VNU-UET")
UNKNOWN_SCHOOL = "unknown"

# Only the first pages go to the classifier; official cover pages name the
# school/year up front, and this caps token cost per file.
CLASSIFY_TEXT_LIMIT = 4000

_YEAR_RE = re.compile(r"\b20\d{2}\b")

CLASSIFY_SYSTEM_PROMPT = (
    "Bạn phân loại tài liệu tuyển sinh đại học Việt Nam. "
    "Chỉ trả về JSON đúng schema, không thêm lời dẫn."
)

CLASSIFY_USER_TEMPLATE = (
    "Cho tên file và nội dung 1-2 trang đầu của một tài liệu PDF tuyển sinh, "
    "xác định trường và năm tuyển sinh.\n"
    '- "school": một trong {schools}, hoặc "unknown" nếu không chắc chắn.\n'
    '- "year": năm tuyển sinh (số nguyên, ví dụ 2026), hoặc null nếu không rõ.\n'
    'Trả về JSON dạng {{"school": "...", "year": 2026}}.\n\n'
    "Tên file: {filename}\n\n"
    "Nội dung:\n{text}"
)


@dataclass
class ResolvedMetadata:
    school: str
    year: int | None
    warnings: list[str] = field(default_factory=list)


def load_overrides(root: Path) -> dict:
    """Read <root>/overrides.json: {"<filename>": {"school": "...", "year": 2026}}."""
    path = Path(root) / "overrides.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def metadata_from_override(entry: dict) -> ResolvedMetadata:
    return ResolvedMetadata(
        school=entry.get("school", UNKNOWN_SCHOOL),
        year=entry.get("year"),
    )


def year_from_filename(filename: str) -> int | None:
    m = _YEAR_RE.search(filename)
    return int(m.group(0)) if m else None


def resolve_metadata(first_pages_text, filename, overrides, gateway):
    raise NotImplementedError


def build_gateway_classifier(gateway=None):
    raise NotImplementedError
