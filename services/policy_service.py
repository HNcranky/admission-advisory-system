from typing import Dict, List, Tuple

from agents.models import (
    CandidateProgram,
    PolicyDecision,
    RankedRecommendation,
    StudentProfile,
)


CRITICAL_PROFILE_SLOTS = {"total_score", "subject_combination", "preferred_majors"}


def _has_valid_evidence(candidate: CandidateProgram) -> bool:
    if not candidate.evidence:
        return False
    return any(bool(ev.source_url) for ev in candidate.evidence)


def evaluate_policy_guardrails(
    user_query: str,
    profile: StudentProfile,
    candidates: List[CandidateProgram],
    recommendations: List[RankedRecommendation],
    conflicts: List[str],
) -> Tuple[PolicyDecision, List[RankedRecommendation]]:
    warnings: List[str] = []
    blocked_claims: List[str] = ["no_guaranteed_admission_claim"]
    policy_flags: List[str] = []

    if profile.total_score is None:
        blocked_claims.append("no_probability_claim_without_score")

    if any(slot in CRITICAL_PROFILE_SLOTS for slot in profile.missing_slots):
        policy_flags.append("missing_critical_profile")
        warnings.append(
            "Cần bổ sung thông tin hồ sơ để tư vấn đáng tin cậy hơn: "
            + ", ".join(sorted(set(profile.missing_slots)))
        )

    if conflicts:
        policy_flags.append("retrieval_conflicts_detected")
        warnings.append("Dữ liệu có mâu thuẫn giữa các nguồn; hãy kiểm tra nguồn chính thức trước khi đăng ký.")

    if not candidates:
        policy_flags.append("empty_retrieval")
        warnings.append("Không tìm thấy chương trình phù hợp trong dữ liệu chuẩn hóa hiện tại.")

    lower_query = user_query.lower()
    if "chac do" in lower_query or "chac chan do" in lower_query:
        blocked_claims.append("no_definitive_admission_answer")

    candidate_map: Dict[str, CandidateProgram] = {
        candidate.candidate_id: candidate for candidate in candidates
    }
    filtered_recommendations: List[RankedRecommendation] = []

    for recommendation in recommendations:
        candidate = candidate_map.get(recommendation.candidate_id)
        if candidate is None:
            continue
        if not _has_valid_evidence(candidate):
            warnings.append(
                f"Đã loại gợi ý {recommendation.candidate_id} vì thiếu nguồn tham chiếu."
            )
            continue
        filtered_recommendations.append(recommendation)

    if recommendations and not filtered_recommendations:
        policy_flags.append("all_recommendations_blocked")
        warnings.append(
            "Tất cả gợi ý đã bị chặn vì thiếu nguồn tham chiếu."
        )

    decision = PolicyDecision(
        allow_answer=True,
        blocked_claims=list(dict.fromkeys(blocked_claims)),
        warnings=list(dict.fromkeys(warnings)),
        policy_flags=list(dict.fromkeys(policy_flags)),
        requires_follow_up=any(slot in CRITICAL_PROFILE_SLOTS for slot in profile.missing_slots),
        allowed_candidate_ids=[rec.candidate_id for rec in filtered_recommendations],
    )
    return decision, filtered_recommendations
