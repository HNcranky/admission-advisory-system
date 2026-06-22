from typing import Dict, List

from ingestion.storage.db_connection import get_connection
from services.db import cursor


class ConflictEvidenceRepository:
    """Read source_url + fetched_at for canonical records (audit §4.5).

    fetched_at is always NULL since the raw_documents/extracted_facts write
    path is not wired in production (audit §1); the column is kept so callers
    that read it keep working unchanged.
    """

    def __init__(self, connection_factory=get_connection):
        self.connection_factory = connection_factory

    def fetch_fetched_at_by_source(
        self, source_urls: List[str], school_id: str, admission_year: int
    ) -> Dict[str, object]:
        sql = """
            SELECT car.source_url, NULL::timestamptz AS fetched_at
            FROM canonical_admission_records car
            WHERE car.source_url = ANY(%s)
              AND car.school_id = %s
              AND car.admission_year = %s
        """
        mapping: Dict[str, object] = {}
        with cursor(self.connection_factory, commit=False) as cur:
            cur.execute(sql, (list(source_urls), school_id, admission_year))
            for source_url, fetched_at in cur.fetchall():
                mapping.setdefault(source_url, fetched_at)  # first row wins per url
        return mapping
