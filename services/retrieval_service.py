import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from agents.models import CandidateProgram, CutoffEntry, Evidence, StudentProfile
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


def fetch_cutoff_history(
    pairs: Set[Tuple[str, Optional[str]]],
) -> Dict[Tuple[str, str], List[CutoffEntry]]:
    """Batch-load lịch sử điểm chuẩn cho các cặp (school_id, program_id).

    Degrade graceful (EC-18 nền): bảng chưa migrate / DB lỗi / row lệch cột →
    log warning + trả {}; KHÔNG bao giờ làm fail retrieval.
    """
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
    try:
        with get_cursor(commit=False) as cur:
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
    except Exception as exc:
        logger.warning(
            "fetch_cutoff_history thất bại — tiếp tục KHÔNG có dữ liệu điểm chuẩn: %r", exc
        )
        return {}
    return history


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
            program_name_raw,
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
                program_name_raw,
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
                    program_name_raw=program_name_raw,
                    admission_method=admission_method,
                    subject_combinations=_to_list(subject_combinations),
                    quota=_to_dict(quota),
                    tuition=_to_dict(tuition),
                    metadata=_to_dict(metadata) or {},
                    evidence=[evidence],
                )
            )

    cutoff_map = fetch_cutoff_history(
        {(c.school_id, c.program_id) for c in candidates if c.program_id}
    )
    for candidate in candidates:
        if candidate.program_id:
            candidate.cutoff_history = cutoff_map.get(
                (candidate.school_id, candidate.program_id), []
            )
    return candidates
