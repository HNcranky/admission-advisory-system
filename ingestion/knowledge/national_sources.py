"""Curated list of official national admission-regulation PDFs (spec §5.1).

Each row is a {"url", "title"} dict; `url` points at an official
datafiles.chinhphu.vn signed PDF. Ingested under the national scope by
`python -m ingestion.knowledge.ingest_national` (Plan 2)."""
import json
from pathlib import Path

_DEFAULT_SEED = Path(__file__).parent / "seeds" / "national_sources.json"


def load_national_sources(path=None) -> list[dict]:
    """Return curated rows with a non-empty `url`; skip malformed rows.
    A missing file yields []."""
    p = Path(path) if path is not None else _DEFAULT_SEED
    if not p.exists():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [r for r in raw if isinstance(r, dict) and r.get("url")]
