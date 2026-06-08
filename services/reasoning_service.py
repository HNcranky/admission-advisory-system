from typing import Dict, List, Tuple

from agents.models import CandidateProgram, EligibilityCheck, RankedRecommendation, StudentProfile
from services.cutoff.assessment import SAFE_MARGIN, assess_cutoff
from services.explanation_service import _fmt_num, _program_label
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


_BAND_TIGHTNESS = {"reach": 0, "match": 1, "safe": 2}  # nhỏ hơn = chặt hơn


def _cap_band(band: str, cap):
    """Hạ band xuống cap nếu band đang lỏng hơn; 'unknown' giữ nguyên."""
    if cap is None or band not in _BAND_TIGHTNESS:
        return band
    return cap if _BAND_TIGHTNESS[band] > _BAND_TIGHTNESS[cap] else band


def _tightest_cap(*caps):
    real = [c for c in caps if c is not None]
    return min(real, key=lambda c: _BAND_TIGHTNESS[c]) if real else None


def _fmt_margin(margin: float) -> str:
    return f"{margin:+g}"


def _apply_assessment(assessment, reasons, cautions, candidate):
    """Bảng WS5 spec: trả (bonus, band_cap); ghi reasons/cautions/data_uncertain tại chỗ.

    decision_changing: caution của nhãn bị THAY bằng dual-value note (phát biểu
    một-nguồn gây hiểu lầm khi nguồn khác nói ngược lại)."""
    bonus = 0.0
    cap = None
    year = assessment.reference_year

    if assessment.score_fit == "above":
        if assessment.margin >= SAFE_MARGIN:
            bonus = 0.10
            reasons.append(
                f"Điểm cao hơn rõ rệt mức tham chiếu {year} ({_fmt_margin(assessment.margin)})."
            )
        else:
            bonus = 0.05
            reasons.append(
                f"Điểm trên mức tham chiếu {year} ({_fmt_margin(assessment.margin)})."
            )
    elif assessment.score_fit == "borderline":
        cap = "match"
        if not assessment.decision_changing:
            cautions.append(
                f"Điểm sát ngưỡng tham chiếu {year} ({_fmt_margin(assessment.margin)}) "
                "— lựa chọn có rủi ro."
            )
    elif assessment.score_fit == "below":
        cap = "reach"
        if not assessment.decision_changing:
            cautions.append(
                f"Điểm thấp hơn mức tham chiếu {year} ({_fmt_margin(assessment.margin)})."
            )
    else:  # "uncertain" — điểm chuẩn biến động (EC-15)
        cap = "match"
        cautions.append(
            f"Điểm chuẩn dao động {_fmt_num(assessment.volatility_min)}–"
            f"{_fmt_num(assessment.volatility_max)} qua {len(assessment.years_used)} năm "
            "gần nhất, chưa thể kết luận."
        )

    if assessment.decision_changing:
        cap = _tightest_cap(cap, "match")
        if "cutoff_score" not in candidate.data_uncertain_fields:
            candidate.data_uncertain_fields.append("cutoff_score")
        values = " / ".join(_fmt_num(v["value"]) for v in assessment.latest_values)
        cautions.append(
            f"Các nguồn ghi khác nhau về điểm chuẩn tham chiếu {year} ({values}); "
            "kết luận thay đổi theo nguồn nên đánh giá ở mức thận trọng."
        )
    return bonus, cap


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
        assessment = None
        cutoff_cap = None

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
                assessment = assess_cutoff(
                    profile.total_score, profile_method, candidate.cutoff_history
                )
                if assessment is not None:
                    bonus, cutoff_cap = _apply_assessment(
                        assessment, reasons, cautions, candidate
                    )
                    score += bonus
                # Fallback heuristic tuyệt đối khi CHƯA có dữ liệu điểm chuẩn.
                elif profile.total_score >= 26:
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
        band = _cap_band(band, cutoff_cap)
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
                cutoff_assessment=assessment,
            )
        )

    order = {"safe": 0, "match": 1, "reach": 2, "unknown": 3}
    recommendations.sort(key=lambda rec: (order.get(rec.band, 99), -rec.score))
    return checks, recommendations


def index_candidates_by_id(candidates: List[CandidateProgram]) -> Dict[str, CandidateProgram]:
    return {candidate.candidate_id: candidate for candidate in candidates}
