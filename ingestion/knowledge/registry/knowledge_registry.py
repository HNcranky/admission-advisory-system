import json
from pathlib import Path

from ingestion.knowledge.registry.models import KnowledgeSource

_DEFAULT_SEED = Path(__file__).parent / "seeds" / "knowledge_sources.json"


class KnowledgeRegistry:
    def __init__(self, seed_path: Path | None = None):
        path = seed_path or _DEFAULT_SEED
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        # Validation (incl. taxonomy) happens here — a bad entry raises.
        self._sources = [KnowledgeSource(**entry) for entry in raw]

    def all_sources(self) -> list[KnowledgeSource]:
        return list(self._sources)

    def get_sources_by_school(self, school: str) -> list[KnowledgeSource]:
        return [s for s in self._sources if s.school == school and s.active]

    def schools(self) -> list[str]:
        seen: list[str] = []
        for s in self._sources:
            if s.school not in seen:
                seen.append(s.school)
        return seen
