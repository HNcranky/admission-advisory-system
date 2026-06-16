from typing import Dict, List, Optional, Set, Tuple

from agents.models import CutoffEntry
from ingestion.storage.db_connection import get_connection
from services.db import cursor


class CutoffRepository:
    """Batch-load cutoff-score history per (school_id, program_id) (audit §4.5)."""

    def __init__(self, connection_factory=get_connection):
        self.connection_factory = connection_factory

    def fetch_cutoff_history(
        self, pairs: Set[Tuple[str, Optional[str]]]
    ) -> Dict[Tuple[str, str], List[CutoffEntry]]:
        clean_pairs = {(s, p) for (s, p) in pairs if s and p}
        if not clean_pairs:
            return {}

        sql = """
            SELECT school_id, program_id, cutoff_year, admission_method,
                   score_scale, cutoff_score, source_url, source_trust_level, note
            FROM cutoff_records
            WHERE (school_id, program_id) IN %s
            ORDER BY cutoff_year DESC, source_trust_level DESC NULLS LAST
        """
        history: Dict[Tuple[str, str], List[CutoffEntry]] = {}
        with cursor(self.connection_factory, commit=False) as cur:
            cur.execute(sql, (tuple(clean_pairs),))
            for row in cur.fetchall():
                (school_id, program_id, cutoff_year, admission_method,
                 score_scale, cutoff_score, source_url, trust_level, note) = row
                history.setdefault((school_id, program_id), []).append(
                    CutoffEntry(
                        cutoff_year=cutoff_year,
                        admission_method=admission_method,
                        cutoff_score=float(cutoff_score),
                        score_scale=float(score_scale) if score_scale is not None else None,
                        source_url=source_url or "",
                        trust_level=trust_level,
                        note=note,
                    )
                )
        return history
