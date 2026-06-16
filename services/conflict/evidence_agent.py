from typing import Dict, List, Optional

from agents.models import CandidateProgram
from services.conflict.models import ConflictRecord, EvidenceOption
from services.conflict.repository import ConflictEvidenceRepository


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


def package_evidence(
    record: ConflictRecord,
    raw_candidates: List[CandidateProgram],
    _evidence_repo: Optional[ConflictEvidenceRepository] = None,
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
    if db_urls:  # all-mock record → no DB lookup at all
        repo = _evidence_repo or ConflictEvidenceRepository()
        try:
            fetched_map = repo.fetch_fetched_at_by_source(
                db_urls, record.school_id, record.admission_year
            )
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
