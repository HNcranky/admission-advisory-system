from typing import Dict, List, Optional

from agents.models import CandidateProgram
from ingestion.storage.db_connection import get_cursor
from services.conflict.models import ConflictRecord, EvidenceOption


def _candidate_by_source(candidates: List[CandidateProgram]) -> Dict[str, CandidateProgram]:
    mapping: Dict[str, CandidateProgram] = {}
    for candidate in candidates:
        for evidence in candidate.evidence:
            mapping[evidence.source_url] = candidate
    return mapping


def _is_mock_source(source_url: str, candidate: Optional[CandidateProgram]) -> bool:
    return source_url.startswith("mock://") or bool(
        candidate and candidate.metadata.get("mock_conflict")
    )


def _enrich_from_db(option: EvidenceOption, record: ConflictRecord) -> EvidenceOption:
    sql = """
        SELECT rd.fetched_at
        FROM canonical_admission_records car
        LEFT JOIN extracted_facts ef ON ef.id = car.extracted_fact_id
        LEFT JOIN raw_documents rd ON rd.id = ef.raw_document_id
        WHERE car.source_url = %s
          AND car.school_id = %s
          AND car.admission_year = %s
        LIMIT 1
    """
    with get_cursor(commit=False) as cur:
        cur.execute(sql, (option.source_url, record.school_id, record.admission_year))
        row = cur.fetchone()
    if row:
        option.fetched_at = row[0]
    return option


def package_evidence(
    record: ConflictRecord,
    raw_candidates: List[CandidateProgram],
) -> List[EvidenceOption]:
    candidates_by_source = _candidate_by_source(raw_candidates)
    packaged: List[EvidenceOption] = []
    for option in record.options:
        candidate = candidates_by_source.get(option.source_url)
        if _is_mock_source(option.source_url, candidate):
            packaged.append(option)
            continue
        try:
            packaged.append(_enrich_from_db(option, record))
        except Exception:
            packaged.append(option)
    return packaged
