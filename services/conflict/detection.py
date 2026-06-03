import json
from collections import defaultdict
from typing import Any, Dict, Hashable, List, Tuple

from agents.models import CandidateProgram
from services.conflict.models import ConflictRecord, EvidenceOption


def _conflict_key(candidate: CandidateProgram) -> Tuple[str, int, str, str]:
    return (
        candidate.school_id,
        candidate.admission_year,
        candidate.program_id or candidate.program_name,
        candidate.admission_method or "unknown_method",
    )


def _conflict_key_text(key: Tuple[str, int, str, str]) -> str:
    return ":".join(str(part) for part in key)


def _normalize_quota_value(quota: Any) -> Hashable:
    if quota is None:
        return ("none", None)
    if isinstance(quota, dict):
        if set(quota.keys()) == {"value"} or {"value", "unit"}.issuperset(quota.keys()):
            return ("value", quota.get("value"), quota.get("unit"))
        return ("json", json.dumps(quota, sort_keys=True, ensure_ascii=False))
    return ("raw", str(quota))


def _option_from_candidate(candidate: CandidateProgram) -> EvidenceOption:
    evidence = candidate.evidence[0] if candidate.evidence else None
    source_url = evidence.source_url if evidence else ""
    value = (
        candidate.quota.get("value")
        if isinstance(candidate.quota, dict) and "value" in candidate.quota
        else candidate.quota
    )
    return EvidenceOption(
        evidence_id=f"{source_url}|quota",
        source_url=source_url,
        trust_level=evidence.trust_level if evidence else None,
        confidence_score=evidence.confidence_score if evidence else None,
        value=value,
    )


def detect_quota_conflicts(candidates: List[CandidateProgram]) -> List[ConflictRecord]:
    groups: Dict[Tuple[str, int, str, str], List[CandidateProgram]] = defaultdict(list)
    for candidate in candidates:
        groups[_conflict_key(candidate)].append(candidate)

    records: List[ConflictRecord] = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        distinct_values = {_normalize_quota_value(candidate.quota) for candidate in group}
        if len(distinct_values) < 2:
            continue
        first = group[0]
        records.append(
            ConflictRecord(
                conflict_key=_conflict_key_text(key),
                field_name="quota",
                school_id=first.school_id,
                school_name=first.school_name,
                admission_year=first.admission_year,
                program_id=first.program_id,
                program_name=first.program_name,
                admission_method=first.admission_method,
                options=[_option_from_candidate(candidate) for candidate in group],
            )
        )
    return records
