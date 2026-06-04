"""Per-school crawl targets for the focused PDF crawler."""
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from ingestion.knowledge.local_metadata import KNOWN_SCHOOLS

_DEFAULT_SEED = Path(__file__).parent / "seeds" / "crawler_targets.json"


class CrawlTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    school: str
    seeds: list[str]
    allow_domains: list[str]
    allow_path_prefixes: list[str] = []
    max_depth: int = 2
    max_pages: int = 300

    @field_validator("school")
    @classmethod
    def _school_known(cls, v: str) -> str:
        if v not in KNOWN_SCHOOLS:
            raise ValueError(f"school {v!r} not in KNOWN_SCHOOLS {KNOWN_SCHOOLS}")
        return v


def load_targets(path: Path | None = None) -> list[CrawlTarget]:
    p = path or _DEFAULT_SEED
    raw = json.loads(Path(p).read_text(encoding="utf-8"))
    return [CrawlTarget(**entry) for entry in raw]
