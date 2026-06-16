"""Nguồn duy nhất cho chuỗi conflict-key (quota + cutoff).

Trước đây logic này lặp ở detection.py, agents/conflict_agent.py và
explanation_service.py. Các chuỗi được so khớp xuyên module nên định dạng phải
ổn định tuyệt đối.
"""
from typing import Tuple

from domain.models import CandidateProgram


def quota_key_tuple(candidate: CandidateProgram) -> Tuple[str, int, str, str]:
    return (
        candidate.school_id,
        candidate.admission_year,
        candidate.program_id or candidate.program_name,
        candidate.admission_method or "unknown_method",
    )


def quota_key_text_from_tuple(key: Tuple[str, int, str, str]) -> str:
    return ":".join(str(part) for part in key)


def quota_key_text(candidate: CandidateProgram) -> str:
    return quota_key_text_from_tuple(quota_key_tuple(candidate))


def cutoff_key_text(school_id: str, cutoff_year: int, program_key: str, method: str) -> str:
    return f"{school_id}:{cutoff_year}:{program_key}:{method}:cutoff"
