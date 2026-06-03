import os
from typing import Any, Dict, List

from agents.models import CandidateProgram, Evidence

MOCK_SCHOOL_ID = "vnu_uet"
MOCK_PROGRAM_ID = "cntt"
MOCK_PROGRAM_NAME = "Cong nghe thong tin"
MOCK_SCHOOL_NAME = "Dai hoc Cong nghe - DHQGHN"
MOCK_METHOD = "thpt_score"
MOCK_DATASET = "advisory_conflict_v1"
TRUTHY_VALUES = {"1", "true", "yes", "on"}


def mock_conflicts_enabled() -> bool:
    return os.getenv("ADVISORY_MOCK_CONFLICTS", "").strip().lower() in TRUTHY_VALUES


def _matches_preferred_schools(filters: Dict[str, Any]) -> bool:
    preferred_schools = filters.get("preferred_schools") or []
    return not preferred_schools or MOCK_SCHOOL_ID in preferred_schools


def _matches_preferred_majors(filters: Dict[str, Any]) -> bool:
    preferred_majors = [
        str(item).lower() for item in (filters.get("preferred_majors") or [])
    ]
    if not preferred_majors:
        return True
    normalized_name = MOCK_PROGRAM_NAME.lower()
    return any(
        major == MOCK_PROGRAM_ID
        or major.replace("_", " ") in normalized_name
        or major in normalized_name
        for major in preferred_majors
    )


def _candidate(
    *,
    year: int,
    quota_value: int,
    source_url: str,
    trust_level: int,
    confidence_score: float,
) -> CandidateProgram:
    quota = {"value": quota_value, "unit": "students"}
    return CandidateProgram(
        candidate_id=f"{MOCK_SCHOOL_ID}:{year}:{MOCK_PROGRAM_ID}:{MOCK_METHOD}",
        school_id=MOCK_SCHOOL_ID,
        school_name=MOCK_SCHOOL_NAME,
        admission_year=year,
        program_id=MOCK_PROGRAM_ID,
        program_name=MOCK_PROGRAM_NAME,
        admission_method=MOCK_METHOD,
        subject_combinations=["A00", "A01"],
        quota=quota,
        tuition={"value": 32000000, "currency": "VND", "period": "year"},
        metadata={"mock_conflict": True, "mock_dataset": MOCK_DATASET},
        evidence=[
            Evidence(
                source_url=source_url,
                school_name=MOCK_SCHOOL_NAME,
                admission_year=year,
                field_name="quota",
                normalized_value=quota,
                confidence_score=confidence_score,
                trust_level=trust_level,
            )
        ],
    )


def build_mock_conflict_candidates(
    filters: Dict[str, Any],
    limit: int = 100,
) -> List[CandidateProgram]:
    if not _matches_preferred_schools(filters):
        return []
    if not _matches_preferred_majors(filters):
        return []

    year = int(filters.get("admission_year") or 2026)
    candidates = [
        _candidate(
            year=year,
            quota_value=120,
            source_url="mock://uet/program-page",
            trust_level=2,
            confidence_score=0.86,
        ),
        _candidate(
            year=year,
            quota_value=150,
            source_url="mock://vnu/proposal-pdf",
            trust_level=3,
            confidence_score=0.94,
        ),
        _candidate(
            year=year,
            quota_value=150,
            source_url="mock://uet/admission-news",
            trust_level=2,
            confidence_score=0.9,
        ),
    ]
    return candidates[:limit]
