from typing import Dict, List, Tuple

from agents.models import CandidateProgram, EligibilityCheck, RankedRecommendation, StudentProfile
from services.explanation_service import _program_label
from services.profile.admission_methods import (
    THANG_30_METHODS,
    candidate_method_codes,
    method_display,
)


def _major_matches(profile: StudentProfile, candidate: CandidateProgram) -> bool:
    if not profile.preferred_majors:
        return False
    lowered_name = candidate.program_name.lower()
    for major_id in profile.preferred_majors:
        if major_id == candidate.program_id:
            return True
        if major_id.replace("_", " ") in lowered_name:
            return True
    return False


def _school_matches(profile: StudentProfile, candidate: CandidateProgram) -> bool:
    if not profile.preferred_schools:
        return False
    return candidate.school_id in profile.preferred_schools


def _score_to_band(score: float, has_missing_critical: bool) -> str:
    if has_missing_critical:
        return "unknown"
    if score >= 0.75:
        return "safe"
    if score >= 0.50:
        return "match"
    return "reach"


def _max_confidence(candidate: CandidateProgram):
    return max(
        [ev.confidence_score for ev in candidate.evidence if ev.confidence_score is not None]
        or [None]
    )


def reason_candidates(
    profile: StudentProfile, candidates: List[CandidateProgram]
) -> Tuple[List[EligibilityCheck], List[RankedRecommendation]]:
    checks: List[EligibilityCheck] = []
    recommendations: List[RankedRecommendation] = []
    profile_method = getattr(profile, "admission_method", None)

    for candidate in candidates:
        score = 0.0
        reasons: List[str] = []
        risks: List[str] = []
        cautions: List[str] = []
        eligible = True

        codes = candidate_method_codes(candidate)
        method_mismatch = bool(profile_method and codes and profile_method not in codes)

        if method_mismatch:
            # Ngả 1 — khác phương thức: xếp theo ngành/trường, KHÔNG đối chiếu
            # điểm/tổ hợp (tổ hợp của row thuộc phương thức khác).
            eligible = None
            cautions.append(
                f"Chương trình này xét theo {candidate.admission_method}, khác phương thức "
                f"em đã chọn ({method_display(profile_method)}); điểm và tổ hợp chưa được đối chiếu."
            )
        elif profile.subject_combination:
            if (
                not candidate.subject_combinations
                or profile.subject_combination in candidate.subject_combinations
            ):
                score += 0.40
                reasons.append("Tổ hợp xét tuyển phù hợp.")
            else:
                # Ngả 2 — NOT_ELIGIBLE (EC-12): ghi check, KHÔNG xếp hạng,
                # KHÔNG tính tiếp score-fit.
                combos = ", ".join(candidate.subject_combinations)
                checks.append(
                    EligibilityCheck(
                        candidate_id=candidate.candidate_id,
                        eligible=False,
                        risks=[
                            f"Chương trình không nhận tổ hợp {profile.subject_combination} "
                            f"theo phương thức đã chọn — các tổ hợp được công bố: {combos}."
                        ],
                        confidence=_max_confidence(candidate),
                    )
                )
                continue
        else:
            eligible = None
            risks.append("Hồ sơ còn thiếu tổ hợp xét tuyển.")

        # Ngả 3 — chấm điểm như cũ, nhưng score-fit bonus chỉ cho thang 30.
        if _major_matches(profile, candidate):
            score += 0.35
            reasons.append("Ngành ưu tiên khớp với chương trình.")

        if _school_matches(profile, candidate):
            score += 0.15
            reasons.append("Trường ưu tiên khớp với nguyện vọng.")

        if profile.total_score is not None:
            if method_mismatch:
                pass  # đã caution ở ngả 1; không đối chiếu điểm
            elif profile_method in THANG_30_METHODS:
                if profile.total_score >= 26:
                    score += 0.10
                    reasons.append("Điểm dự kiến đang ở mức cạnh tranh tốt.")
                elif profile.total_score >= 24:
                    score += 0.05
                    reasons.append("Điểm dự kiến đang ở mức có thể cân nhắc.")
                else:
                    cautions.append(
                        "Điểm dự kiến có thể thấp hơn mức cạnh tranh của một số chương trình."
                    )
            elif profile_method is None:
                cautions.append("Hồ sơ chưa rõ phương thức xét tuyển nên chưa đánh giá mức điểm.")
            else:
                cautions.append(
                    f"Điểm theo {method_display(profile_method)} chưa thể đối chiếu trực tiếp "
                    "với dữ liệu tham chiếu hiện có."
                )
        else:
            cautions.append("Hồ sơ còn thiếu điểm nên chưa thể ước lượng mức cạnh tranh.")

        has_missing_critical = bool(profile.missing_slots)
        band = _score_to_band(score, has_missing_critical)
        if "quota" in candidate.data_uncertain_fields:
            if band == "safe":
                band = "match"
            cautions.append("Dữ liệu hạn ngạch chưa được xác minh giữa các nguồn.")
        summary = f"{_program_label(candidate)} tại {candidate.school_name}: mức phù hợp {band}."

        checks.append(
            EligibilityCheck(
                candidate_id=candidate.candidate_id,
                eligible=eligible,
                reasons=reasons,
                risks=risks,
                confidence=_max_confidence(candidate),
            )
        )
        recommendations.append(
            RankedRecommendation(
                candidate_id=candidate.candidate_id,
                band=band,
                score=round(score, 3),
                summary=summary,
                reasons=reasons,
                cautions=risks + cautions,
            )
        )

    order = {"safe": 0, "match": 1, "reach": 2, "unknown": 3}
    recommendations.sort(key=lambda rec: (order.get(rec.band, 99), -rec.score))
    return checks, recommendations


def index_candidates_by_id(candidates: List[CandidateProgram]) -> Dict[str, CandidateProgram]:
    return {candidate.candidate_id: candidate for candidate in candidates}
