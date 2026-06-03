import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from agents.models import CandidateProgram, Evidence, StudentProfile
from ingestion.storage.db_connection import get_cursor
from services.mock_retrieval import (
    build_mock_conflict_candidates,
    mock_conflicts_enabled,
)

logger = logging.getLogger(__name__)


def _to_dict(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
            return loaded if isinstance(loaded, dict) else {"value": loaded}
        except json.JSONDecodeError:
            return {"raw": value}
    return {"value": value}


def _to_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, str):
        try:
            loaded = json.loads(value)
            if isinstance(loaded, list):
                items = loaded
            else:
                return [value]
        except json.JSONDecodeError:
            return [value]
    else:
        return [str(value)]
    return [item["code"] if isinstance(item, dict) and "code" in item else str(item) for item in items]


def build_retrieval_filters(profile: StudentProfile, admission_year: int) -> Dict[str, Any]:
    return {
        "admission_year": admission_year,
        "preferred_majors": profile.preferred_majors,
        "preferred_schools": profile.preferred_schools,
        "subject_combination": profile.subject_combination,
    }


def fetch_candidates(filters: Dict[str, Any], limit: int = 100) -> List[CandidateProgram]:
    # ADVISORY_MOCK_CONFLICTS keeps local/demo conflict retrieval off the DB path.
    if mock_conflicts_enabled():
        logger.warning(
            "ADVISORY_MOCK_CONFLICTS is enabled: bypassing the database and "
            "returning in-memory mock conflict candidates. Do NOT use in production."
        )
        return build_mock_conflict_candidates(filters=filters, limit=limit)

    where_clauses: List[str] = ["admission_year = %s"]
    params: List[Any] = [filters["admission_year"]]

    preferred_schools = filters.get("preferred_schools") or []
    if preferred_schools:
        where_clauses.append("school_id = ANY(%s)")
        params.append(preferred_schools)

    preferred_majors = filters.get("preferred_majors") or []
    if preferred_majors:
        where_clauses.append("(program_id = ANY(%s) OR program_name_canonical ILIKE ANY(%s))")
        params.append(preferred_majors)
        params.append([f"%{major.replace('_', ' ')}%" for major in preferred_majors])

    sql = f"""
        SELECT
            school_id,
            school_name_canonical,
            admission_year,
            program_id,
            program_name_canonical,
            admission_method,
            subject_combinations,
            quota,
            tuition,
            metadata,
            source_url,
            source_trust_level,
            confidence_score
        FROM canonical_admission_records
        WHERE {' AND '.join(where_clauses)}
        ORDER BY source_trust_level DESC NULLS LAST, confidence_score DESC NULLS LAST
        LIMIT %s
    """
    params.append(limit)

    candidates: List[CandidateProgram] = []
    with get_cursor(commit=False) as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        for row in rows:
            (
                school_id,
                school_name,
                admission_year,
                program_id,
                program_name,
                admission_method,
                subject_combinations,
                quota,
                tuition,
                metadata,
                source_url,
                source_trust_level,
                confidence_score,
            ) = row

            evidence = Evidence(
                source_url=source_url or "",
                school_name=school_name or "",
                admission_year=admission_year,
                field_name="canonical_admission_record",
                normalized_value={
                    "program_id": program_id,
                    "program_name": program_name,
                    "admission_method": admission_method,
                },
                confidence_score=confidence_score,
                trust_level=source_trust_level,
            )

            candidate_id = ":".join(
                [
                    school_id or "unknown_school",
                    str(admission_year),
                    program_id or (program_name or "unknown_program"),
                    admission_method or "unknown_method",
                ]
            )
            candidates.append(
                CandidateProgram(
                    candidate_id=candidate_id,
                    school_id=school_id or "unknown_school",
                    school_name=school_name or "",
                    admission_year=admission_year,
                    program_id=program_id,
                    program_name=program_name or "",
                    admission_method=admission_method,
                    subject_combinations=_to_list(subject_combinations),
                    quota=_to_dict(quota),
                    tuition=_to_dict(tuition),
                    metadata=_to_dict(metadata) or {},
                    evidence=[evidence],
                )
            )
    return candidates


def detect_conflicts(candidates: List[CandidateProgram]) -> List[str]:
    grouped: Dict[Tuple[str, str, str], CandidateProgram] = {}
    conflicts: List[str] = []
    for candidate in candidates:
        key = (
            candidate.school_id,
            candidate.program_id or candidate.program_name,
            candidate.admission_method or "unknown_method",
        )
        previous = grouped.get(key)
        if previous is None:
            grouped[key] = candidate
            continue

        if previous.quota != candidate.quota:
            conflicts.append(
                f"Quota conflict for {candidate.program_name} at {candidate.school_name}"
            )
        if sorted(previous.subject_combinations) != sorted(candidate.subject_combinations):
            conflicts.append(
                f"Subject-combination conflict for {candidate.program_name} at {candidate.school_name}"
            )
    return list(dict.fromkeys(conflicts))
