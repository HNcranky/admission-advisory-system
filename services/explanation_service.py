from typing import Any, Dict, List, Optional

from agents.models import (
    CandidateProgram,
    EligibilityCheck,
    PolicyDecision,
    RankedRecommendation,
    StudentProfile,
)
from services.conflict.models import ResolutionOutcome
from services.conflict.source_labels import label_for_source
from services.formatting import fmt_num as _fmt_num, program_label as _program_label
from services.profile.admission_methods import method_display


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

# Nhãn mức phù hợp hiển thị cho người dùng (theo happy-path Turn 6). band nội bộ
# từ reasoning_service (_score_to_band): safe/match/reach/unknown.
BAND_FIT_LABELS = {
    "safe": "Cao / An toàn",
    "match": "Phù hợp",
    "reach": "Cần cân nhắc",
    "unknown": "Chưa đủ dữ liệu",
}

_CONSOLIDATED_CONFLICT_CAVEAT = (
    "**Lưu ý dữ liệu:** Một số chương trình dưới đây có dữ liệu chưa thống nhất giữa "
    "các nguồn; bạn nên đối chiếu thông báo tuyển sinh chính thức mới nhất của trường "
    "trước khi đăng ký."
)

# Nhãn slot cho câu thông báo correction (AC7).
_SLOT_LABELS = {
    "total_score": "điểm dự kiến",
    "admission_method": "phương thức xét tuyển",
    "location_preference": "khu vực mong muốn",
    "subject_combination": "tổ hợp xét tuyển",
    "tuition_budget": "mức học phí",
    "admission_year": "năm xét tuyển",
    "preferred_majors": "ngành ưu tiên",
}

_FIELD_LABELS = {
    "quota": "chỉ tiêu tuyển sinh",
    "subject_combinations": "tổ hợp xét tuyển",
    "tuition": "học phí",
    "cutoff_score": "điểm chuẩn",
}

CLOSING_VARIANTS = [
    # [0] giữ nguyên chuỗi slice 3a để seed 0 không đổi hành vi.
    "Bạn có muốn ưu tiên theo tiêu chí nào hơn: **khả năng trúng tuyển**, "
    "**đúng sở thích**, hay **học phí an toàn nhất**?",
    "Giữa **khả năng trúng tuyển**, **đúng sở thích** và **học phí an toàn nhất**, "
    "bạn muốn mình ưu tiên tiêu chí nào?",
    "Bạn muốn mình sắp xếp ưu tiên theo **khả năng trúng tuyển**, **đúng sở thích** "
    "hay **học phí an toàn nhất**?",
]

# Câu dẫn mở đầu theo band của đề xuất tốt nhất (3d). Mặc định cho reach/unknown.
_BAND_INTRO_LEAD = {
    "safe": "Hồ sơ của bạn đang khá cạnh tranh.",
    "match": "Hồ sơ của bạn có một số lựa chọn phù hợp.",
}
_DEFAULT_INTRO_LEAD = "Có một vài lựa chọn bạn nên cân nhắc kỹ."


def _translate(text: str) -> str:
    return REASON_TRANSLATIONS.get(text, text)


def _field_label(name: str) -> str:
    return _FIELD_LABELS.get(name, name)




def _cutoff_reference_line(assessment) -> str:
    """'Điểm chuẩn tham chiếu {year}: v1 (nguồn A) / v2 (nguồn B)' — EC-16 dual display."""
    values = " / ".join(
        f"{_fmt_num(v['value'])} ({label_for_source(v['source_url'])})"
        for v in assessment.latest_values
    )
    return f"Điểm chuẩn tham chiếu {assessment.reference_year}: {values}"


def _candidate_conflict_key(candidate: CandidateProgram) -> str:
    """Khớp đúng key conflict_agent dùng (agents/conflict_agent.py:_mark_uncertain)."""
    return ":".join(
        [
            candidate.school_id,
            str(candidate.admission_year),
            candidate.program_id or candidate.program_name,
            candidate.admission_method or "unknown_method",
        ]
    )


def _correction_sentence(note: Dict[str, Any]) -> str:
    slot = note.get("slot")
    prev = note.get("previous_value")
    new = note.get("new_value")
    label = _SLOT_LABELS.get(slot, slot or "thông tin")
    direction = "thành"
    if isinstance(prev, (int, float)) and isinstance(new, (int, float)):
        direction = "xuống" if new < prev else ("lên" if new > prev else "thành")
    return (
        f"Mình đã cập nhật {label} của bạn từ {_fmt_num(prev)} {direction} {_fmt_num(new)}. "
        "Với dữ liệu mới, thứ tự ưu tiên thay đổi:"
    )


def _intro_paragraph(profile: StudentProfile, admission_year: Optional[int], n: int,
                     top_band: Optional[str] = None) -> str:
    lead = _BAND_INTRO_LEAD.get(top_band, _DEFAULT_INTRO_LEAD)
    facts: List[str] = []
    if admission_year:
        facts.append(f"xét tuyển năm {admission_year}")
    if getattr(profile, "admission_method", None):
        facts.append(f"phương thức {method_display(profile.admission_method)}")
    if profile.total_score is not None:
        facts.append(f"dự kiến {_fmt_num(profile.total_score)} điểm")
    if profile.subject_combination:
        facts.append(f"tổ hợp {profile.subject_combination}")
    if profile.preferred_majors:
        facts.append("ưu tiên " + ", ".join(profile.preferred_majors[:3]))
    if profile.location_preference:
        facts.append(f"muốn học tại {profile.location_preference}")
    if profile.tuition_budget:
        facts.append(f"học phí {profile.tuition_budget}")
    if facts:
        return (
            f"{lead} Dựa trên hồ sơ hiện tại của bạn — {', '.join(facts)} — "
            f"mình đề xuất {n} lựa chọn sau:"
        )
    return f"{lead} Dựa trên thông tin hiện có, mình đề xuất {n} lựa chọn sau:"


def _profile_criteria(profile: StudentProfile, admission_year: Optional[int]) -> List[str]:
    facts: List[str] = []
    if admission_year:
        facts.append(f"năm {admission_year}")
    if getattr(profile, "admission_method", None):
        facts.append(f"phương thức {method_display(profile.admission_method)}")
    if profile.total_score is not None:
        facts.append(f"mức điểm {_fmt_num(profile.total_score)}")
    if profile.subject_combination:
        facts.append(f"tổ hợp {profile.subject_combination}")
    if profile.preferred_majors:
        facts.append("ngành " + ", ".join(profile.preferred_majors[:3]))
    if profile.location_preference:
        facts.append(f"khu vực {profile.location_preference}")
    if profile.tuition_budget:
        facts.append(f"ngân sách {profile.tuition_budget}")
    return facts


def _no_match_block(
    profile: StudentProfile,
    admission_year: Optional[int],
    eligibility_checks: List[EligibilityCheck],
) -> List[str]:
    """EC-24: nói rõ tiêu chí đang áp, nguyên nhân (nếu biết) và gợi ý nới minh bạch.
    KHÔNG bịa chương trình; KHÔNG tự nới tiêu chí."""
    facts = _profile_criteria(profile, admission_year)
    lines: List[str] = []
    if facts:
        lines.append(
            "Mình chưa tìm thấy chương trình đáp ứng đồng thời: "
            + "; ".join(facts) + " — trong dữ liệu hiện có."
        )
    else:
        lines.append("Mình chưa tìm thấy chương trình phù hợp trong dữ liệu hiện có.")

    not_eligible = [c for c in eligibility_checks if c.eligible is False]
    if not_eligible and profile.subject_combination:
        majors = ", ".join(profile.preferred_majors[:3]) or "bạn quan tâm"
        lines.append("")
        lines.append(
            f"Các chương trình ngành {majors} trong dữ liệu hiện không nhận tổ hợp "
            f"{profile.subject_combination}; bạn có thể cân nhắc tổ hợp khác hoặc ngành gần."
        )
        return lines

    suggestions: List[str] = []
    if profile.preferred_majors:
        suggestions.append("mở rộng sang ngành gần")
    if profile.location_preference:
        suggestions.append("nới khu vực học")
    if profile.tuition_budget:
        suggestions.append("điều chỉnh ngân sách")
    if suggestions:
        lines.append("")
        lines.append(
            "Bạn có thể cân nhắc: " + "; ".join(suggestions)
            + ". Mình sẽ không tự nới tiêu chí khi chưa có xác nhận của bạn."
        )
    return lines


def _data_note(candidate: CandidateProgram, outcome_by_key: Dict[str, ResolutionOutcome],
               concise: bool = False) -> Optional[str]:
    """Khối '**Lưu ý dữ liệu:**' theo từng chương trình (AC6).

    concise=True bỏ câu nhắc 'kiểm tra thông báo chính thức' (đã gộp lên đầu khi
    ≥2 chương trình mâu thuẫn — 3e)."""
    outcome = outcome_by_key.get(_candidate_conflict_key(candidate))
    if outcome is None and not candidate.data_uncertain_fields:
        return None

    if outcome is not None and outcome.status == "resolved" and outcome.chosen_evidence:
        field = _field_label(outcome.field_name)
        chosen = outcome.chosen_evidence
        all_options = [chosen] + list(outcome.rejected_evidence)
        values = " và ".join(
            f"{_fmt_num(o.value)} ({label_for_source(o.source_url)})" for o in all_options
        )
        note = (
            f"**Lưu ý dữ liệu:** Các nguồn ghi khác nhau về {field}: {values}. "
            f"Hệ thống tham chiếu giá trị {_fmt_num(outcome.resolved_value)} từ "
            f"{label_for_source(chosen.source_url)}"
        )
        if concise:
            return note + "."
        return note + (
            ", nhưng bạn nên kiểm tra thông báo tuyển sinh chính thức mới nhất của "
            "trường trước khi đăng ký."
        )

    if outcome is not None:
        field = _field_label(outcome.field_name)
    else:
        field = ", ".join(_field_label(f) for f in candidate.data_uncertain_fields)
    base = f"**Lưu ý dữ liệu:** Thông tin về {field} đang mâu thuẫn giữa các nguồn."
    if concise:
        return base
    return base + " Bạn nên kiểm tra trực tiếp với trường trước khi đăng ký."


def _not_eligible_lines(
    eligibility_checks: List[EligibilityCheck],
    candidates_by_id: Dict[str, List[CandidateProgram]],
) -> List[str]:
    """Section 'Không đủ điều kiện xét tuyển' (EC-12): cap 3, dedupe theo chương trình."""
    lines: List[str] = []
    seen = set()
    for check in eligibility_checks or []:
        if check.eligible is not False:
            continue
        group = candidates_by_id.get(check.candidate_id, [])
        if not group:
            continue
        candidate = group[0]
        key = (candidate.school_id, candidate.program_id or candidate.program_name)
        if key in seen:
            continue
        seen.add(key)
        reason = check.risks[0] if check.risks else "Không đáp ứng điều kiện xét tuyển đã công bố."
        lines.append(f"- {candidate.school_name} — {_program_label(candidate)}: {reason}")
        if len(lines) >= 3:
            break
    return lines


def build_explanation(
    profile: StudentProfile,
    recommendations: List[RankedRecommendation],
    candidates: List[CandidateProgram],
    policy: Optional[PolicyDecision],
    resolution_outcomes: Optional[List[ResolutionOutcome]] = None,
    admission_year: Optional[int] = None,
    correction_note: Optional[Dict[str, Any]] = None,
    eligibility_checks: Optional[List[EligibilityCheck]] = None,
    closing_seed: int = 0,
) -> str:
    resolution_outcomes = resolution_outcomes or []
    lines: List[str] = []

    if correction_note:
        lines.append(_correction_sentence(correction_note))
        lines.append("")

    candidates_by_id: Dict[str, List[CandidateProgram]] = {}
    for candidate in candidates:
        candidates_by_id.setdefault(candidate.candidate_id, []).append(candidate)

    # Dedup các đề xuất theo candidate_id, giữ thứ tự, cap 5; chỉ giữ rec có candidate.
    renderable: List[tuple] = []
    seen_ids = set()
    for recommendation in recommendations:
        if recommendation.candidate_id in seen_ids:
            continue
        seen_ids.add(recommendation.candidate_id)
        group = candidates_by_id.get(recommendation.candidate_id, [])
        if not group:
            continue
        renderable.append((recommendation, group[0]))
        if len(renderable) >= 5:
            break

    outcome_by_key = {o.conflict_key: o for o in resolution_outcomes}

    if renderable:
        top_band = renderable[0][0].band
        lines.append(_intro_paragraph(profile, admission_year, len(renderable), top_band))
        ref_years = sorted({
            rec.cutoff_assessment.reference_year
            for rec, _candidate in renderable
            if rec.cutoff_assessment is not None
        })
        if ref_years and policy and "historical_cutoff_reference" in policy.policy_flags:
            years_text = ", ".join(str(y) for y in ref_years)
            target = f"năm {admission_year}" if admission_year else "sắp tới"
            lines.append("")
            lines.append(
                f"Chưa có điểm chuẩn chính thức cho kỳ tuyển sinh {target}. "
                f"Đánh giá dưới đây sử dụng dữ liệu năm {years_text} làm tham chiếu "
                "và có thể thay đổi khi trường công bố thông tin mới."
            )
        conflicted = [c for _rec, c in renderable if _data_note(c, outcome_by_key) is not None]
        consolidate = len(conflicted) >= 2
        if consolidate:
            lines.append("")
            lines.append(_CONSOLIDATED_CONFLICT_CAVEAT)
        for idx, (recommendation, candidate) in enumerate(renderable, start=1):
            lines.append("")
            lines.append(f"### {idx}. {candidate.school_name} — {_program_label(candidate)}")
            lines.append("")
            lines.append(f"**Mức phù hợp: {BAND_FIT_LABELS.get(recommendation.band, recommendation.band)}**")

            bullets = [_translate(r) for r in recommendation.reasons[:3]]
            bullets += [_translate(c) for c in recommendation.cautions[:3]]
            if recommendation.cutoff_assessment is not None and recommendation.cutoff_assessment.latest_values:
                bullets.append(_cutoff_reference_line(recommendation.cutoff_assessment))
            if bullets:
                lines.append("")
                for bullet in bullets:
                    lines.append(f"- {bullet}")

            note = _data_note(candidate, outcome_by_key, concise=consolidate)
            if note:
                lines.append("")
                lines.append(note)
    else:
        lines.extend(_no_match_block(profile, admission_year, eligibility_checks or []))

    # Section "Không đủ điều kiện xét tuyển" (EC-12) — render cả khi có lẫn khi
    # không có đề xuất (policy_agent ghi đè ranked_recommendations nên các
    # chương trình NOT_ELIGIBLE không còn trong danh sách đề xuất).
    ne_lines = _not_eligible_lines(eligibility_checks or [], candidates_by_id)
    if ne_lines:
        lines.append("")
        lines.append("Một vài chương trình bạn quan tâm chưa đáp ứng điều kiện xét tuyển:")
        lines.append("")
        lines.append("**Không đủ điều kiện xét tuyển**")
        lines.append("")
        lines.extend(ne_lines)

    # Nguồn tham chiếu (dedup URL theo các đề xuất hiển thị).
    cited_sources: List[str] = []
    for recommendation, _candidate in renderable:
        for candidate in candidates_by_id.get(recommendation.candidate_id, []):
            for evidence in candidate.evidence:
                if evidence.source_url and evidence.source_url not in cited_sources:
                    cited_sources.append(evidence.source_url)
    if cited_sources:
        lines.append("")
        lines.append("**Nguồn tham chiếu**")
        lines.append("")
        for source in cited_sources[:5]:
            lines.append(f"- {source}")

    if policy and policy.warnings:
        lines.append("")
        lines.append("**Cảnh báo**")
        lines.append("")
        for warning in policy.warnings:
            lines.append(f"- {_translate(warning)}")

    if policy and policy.requires_follow_up:
        lines.append("")
        lines.append(
            "Thông tin cần bổ sung: điểm, tổ hợp môn, ngành/trường ưu tiên để nâng độ chính xác."
        )

    if renderable and not correction_note:
        lines.append("")
        lines.append(CLOSING_VARIANTS[closing_seed % len(CLOSING_VARIANTS)])

    return "\n".join(lines)
