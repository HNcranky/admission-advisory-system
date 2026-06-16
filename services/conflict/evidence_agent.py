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


def _batch_fetched_at(source_urls: List[str], record: ConflictRecord) -> Dict[str, object]:
    """One query mapping source_url -> fetched_at for this record's school/year.

    Drops the per-option LIMIT 1, so a source_url with several canonical rows can
    return several rows; the first wins (fetched_at is a property of the source
    document, consistent across that URL's rows)."""
    sql = """
        SELECT car.source_url, NULL::timestamptz AS fetched_at
        FROM canonical_admission_records car
        WHERE car.source_url = ANY(%s)
          AND car.school_id = %s
          AND car.admission_year = %s
    """
    mapping: Dict[str, object] = {}
    with get_cursor(commit=False) as cur:
        cur.execute(sql, (list(source_urls), record.school_id, record.admission_year))
        for source_url, fetched_at in cur.fetchall():
            mapping.setdefault(source_url, fetched_at)  # first row wins per url
    return mapping


def package_evidence(
    record: ConflictRecord,
    raw_candidates: List[CandidateProgram],
) -> List[EvidenceOption]:
    candidates_by_source = _candidate_by_source(raw_candidates)

    # Partition: mock options skip the DB; real options get ONE batched lookup.
    db_urls = [
        option.source_url
        for option in record.options
        if not _is_mock_source(
            option.source_url, candidates_by_source.get(option.source_url)
        )
    ]

    fetched_map: Dict[str, object] = {}
    if db_urls:  # all-mock record → no cursor opened at all
        try:
            fetched_map = _batch_fetched_at(db_urls, record)
        except Exception:
            fetched_map = {}  # DB down → leave options un-enriched, as before

    packaged: List[EvidenceOption] = []
    for option in record.options:
        candidate = candidates_by_source.get(option.source_url)
        if _is_mock_source(option.source_url, candidate):
            packaged.append(option)
            continue
        if option.source_url in fetched_map:
            option.fetched_at = fetched_map[option.source_url]
        packaged.append(option)
    return packaged
