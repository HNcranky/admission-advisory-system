                             

import json
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from ingestion.registry.models import SourceEntry, SourceType, FetchStrategy


class SourceRegistry:
    """
    In-memory source registry backed by a JSON seed file.
    Manages all known admission data sources.

    For production, this would be backed by PostgreSQL,
    but for now we keep it simple with JSON + in-memory.
    """

    def __init__(self, seed_path: Optional[Path] = None):
        self._sources: dict[str, SourceEntry] = {}
        if seed_path and seed_path.exists():
            self._load_seed(seed_path)

    def _load_seed(self, path: Path):
        """Load sources from a JSON seed file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            entry = SourceEntry(**item)
            self._sources[entry.source_id] = entry

                                                                  

    def register_source(self, entry: SourceEntry) -> None:
        """Register a new source."""
        self._sources[entry.source_id] = entry

    def get_source(self, source_id: str) -> Optional[SourceEntry]:
        """Get a source by its ID."""
        return self._sources.get(source_id)

    def get_sources_by_school(self, school_id: str) -> List[SourceEntry]:
        """Get all sources for a given school."""
        return [
            s for s in self._sources.values()
            if s.school_id == school_id
        ]

    def get_active_sources(self) -> List[SourceEntry]:
        """Get all active sources."""
        return [s for s in self._sources.values() if s.active]

    def get_sources_for_crawl(self) -> List[SourceEntry]:
        """
        Get sources that should be crawled, ordered by priority.
        Lower priority number = crawl first.
        """
        active = self.get_active_sources()
        return sorted(active, key=lambda s: s.priority)

    def get_sources_by_type(
        self, source_type: SourceType
    ) -> List[SourceEntry]:
        """Get all sources of a given type."""
        return [
            s for s in self._sources.values()
            if s.source_type == source_type and s.active
        ]

    def update_last_fetched(
        self, source_id: str, fetched_at: Optional[datetime] = None
    ) -> None:
        """Update the last_fetched_at timestamp for a source."""
        source = self._sources.get(source_id)
        if source:
            source.last_fetched_at = fetched_at or datetime.now()

    def deactivate_source(self, source_id: str) -> None:
        """Disable a source."""
        source = self._sources.get(source_id)
        if source:
            source.active = False

    def all_sources(self) -> List[SourceEntry]:
        """Get all sources."""
        return list(self._sources.values())

    def count(self) -> int:
        """Number of registered sources."""
        return len(self._sources)
