from typing import Dict, List, Optional

from agents.models import CandidateProgram, PolicyDecision, RankedRecommendation, StudentProfile
from services.conflict.models import ResolutionOutcome
from services.conflict.source_labels import label_for_source


REASON_TRANSLATIONS = {
    "Subject combination appears compatible.": "Tổ hợp xét tuyển phù hợp.",
    "Preferred major matches candidate program.": "Ngành ưu tiên khớp với chương trình.",
    "Preferred school matches candidate school.": "Trường ưu tiên khớp với nguyện vọng.",
    "Profile score is in a strong range.": "Điểm dự kiến đang ở mức cạnh tranh tốt.",
    "Profile score is in a moderate range.": "Điểm dự kiến đang ở mức có thể cân nhắc.",
    "Subject combination does not match listed combinations.": "Tổ hợp xét tuyển không khớp với các tổ hợp được công bố.",
    "Missing subject combination in profile.": "Hồ sơ còn thiếu tổ hợp xét tuyển.",
    "Profile score may be below highly competitive ranges.": "Điểm dự kiến có thể thấp hơn mức cạnh tranh của một số chương trình.",
    "Missing score; cannot estimate competitiveness reliably.": "Hồ sơ còn thiếu điểm nên chưa thể ước lượng mức cạnh tranh.",
    "So lieu han ngach chua duoc xac nhan giua cac nguon.": "Dữ liệu hạn ngạch chưa được xác minh giữa các nguồn.",
    "Check official cutoff updates.": "Nên kiểm tra điểm chuẩn và thông báo chính thức mới nhất.",
    "Conflicting records detected; verify official source before applying.": "Dữ liệu có mâu thuẫn giữa các nguồn; hãy kiểm tra nguồn chính thức trước khi đăng ký.",
    "No matching programs found in current canonical records.": "Không tìm thấy chương trình phù hợp trong dữ liệu chuẩn hóa hiện tại.",
}

BAND_LABELS = {
    "safe": "an toàn",
    "match": "phù hợp",
    "reach": "cần cân nhắc",
    "unknown": "chưa đủ dữ liệu",
}


def _translate(text: str) -> str:
    return REASON_TRANSLATIONS.get(text, text)


def _profile_summary(profile: StudentProfile) -> str:
    lines = ["Hồ sơ hiện tại"]
    if profile.total_score is not None:
        lines.append(f"- Điểm: {profile.total_score}")
    if profile.subject_combination:
        lines.append(f"- Tổ hợp: {profile.subject_combination}")
    if profile.preferred_majors:
        lines.append("- Ngành ưu tiên: " + ", ".join(profile.preferred_majors[:3]))
    if profile.preferred_schools:
        lines.append("- Trường ưu tiên: " + ", ".join(profile.preferred_schools[:3]))
    if len(lines) == 1:
        lines.append("- Chưa thu thập đủ dữ liệu hồ sơ.")
    return "\n".join(lines)


def build_explanation(
    profile: StudentProfile,
    recommendations: List[RankedRecommendation],
    candidates: List[CandidateProgram],
    policy: Optional[PolicyDecision],
    resolution_outcomes: Optional[List[ResolutionOutcome]] = None,
) -> str:
    lines: List[str] = []
    lines.append(_profile_summary(profile))

    candidates_by_id: Dict[str, List[CandidateProgram]] = {}
    for candidate in candidates:
        candidates_by_id.setdefault(candidate.candidate_id, []).append(candidate)

    if recommendations:
        lines.append("")
        lines.append("Gợi ý chương trình phù hợp")
        displayed_recommendations: List[RankedRecommendation] = []
        displayed_ids = set()
        for recommendation in recommendations:
            if recommendation.candidate_id in displayed_ids:
                continue
            displayed_recommendations.append(recommendation)
            displayed_ids.add(recommendation.candidate_id)

        for idx, recommendation in enumerate(displayed_recommendations[:5], start=1):
            candidate_group = candidates_by_id.get(recommendation.candidate_id, [])
            candidate = candidate_group[0] if candidate_group else None
            if not candidate:
                continue
            lines.append(
                f"{idx}. {candidate.program_name} - {candidate.school_name}"
            )
            lines.append(f"   Mức phù hợp: {BAND_LABELS.get(recommendation.band, recommendation.band)}")
            lines.append(f"   Điểm phù hợp: {recommendation.score}")
            if recommendation.reasons:
                lines.append("   Lý do:")
                for reason in recommendation.reasons[:3]:
                    lines.append(f"   - {_translate(reason)}")
            if recommendation.cautions:
                lines.append("   Lưu ý:")
                for caution in recommendation.cautions[:3]:
                    lines.append(f"   - {_translate(caution)}")
    else:
        lines.append("")
        lines.append("Chưa có đề xuất phù hợp từ dữ liệu hiện tại.")

    cited_sources: List[str] = []
    cited_ids = set()
    for recommendation in recommendations:
        if recommendation.candidate_id in cited_ids:
            continue
        cited_ids.add(recommendation.candidate_id)
        for candidate in candidates_by_id.get(recommendation.candidate_id, []):
            for evidence in candidate.evidence:
                if evidence.source_url:
                    cited_sources.append(evidence.source_url)

    if cited_sources:
        lines.append("")
        lines.append("Nguồn tham chiếu")
        for idx, source in enumerate(list(dict.fromkeys(cited_sources))[:5], start=1):
            lines.append(f"- [{idx}] {source}")

    if policy and policy.warnings:
        lines.append("")
        lines.append("Cảnh báo")
        for warning in policy.warnings:
            lines.append(f"- {_translate(warning)}")

    if policy and policy.requires_follow_up:
        lines.append("")
        lines.append(
            "Thông tin cần bổ sung: điểm, tổ hợp môn, ngành/trường ưu tiên để nâng độ chính xác."
        )

    lines.extend(_verification_lines(resolution_outcomes or []))

    return "\n".join(lines)


def _verification_lines(outcomes: List[ResolutionOutcome]) -> List[str]:
    if not outcomes:
        return []
    lines = ["", "Xác minh dữ liệu"]
    for outcome in outcomes:
        if outcome.status == "resolved" and outcome.chosen_evidence:
            lines.append(
                f"- Hạn ngạch ngành {outcome.program_name} tại {outcome.school_name}: "
                f"hệ thống tìm thấy nhiều nguồn khác nhau. Sử dụng giá trị "
                f"{outcome.resolved_value} từ {label_for_source(outcome.chosen_evidence.source_url)} "
                f"vì {', '.join(outcome.decision_axes) or outcome.rationale}."
            )
        else:
            lines.append(
                f"- Hạn ngạch ngành {outcome.program_name} tại {outcome.school_name}: "
                "thông tin mâu thuẫn giữa các nguồn. Bạn nên xác minh trực tiếp với trường trước khi đăng ký."
            )
    return lines
