from typing import Any, Dict, List, Optional

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

# Nhãn mức phù hợp hiển thị cho người dùng (theo happy-path Turn 6). band nội bộ
# từ reasoning_service (_score_to_band): safe/match/reach/unknown.
BAND_FIT_LABELS = {
    "safe": "Cao / An toàn",
    "match": "Phù hợp",
    "reach": "Cần cân nhắc",
    "unknown": "Chưa đủ dữ liệu",
}

# Nhãn slot cho câu thông báo correction (AC7).
_SLOT_LABELS = {
    "total_score": "điểm dự kiến",
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
}

CLOSING_QUESTION = (
    "Em có muốn ưu tiên theo tiêu chí nào hơn: **khả năng trúng tuyển**, "
    "**đúng sở thích**, hay **học phí an toàn nhất**?"
)


def _translate(text: str) -> str:
    return REASON_TRANSLATIONS.get(text, text)


def _field_label(name: str) -> str:
    return _FIELD_LABELS.get(name, name)


def _fmt_num(value: Any) -> str:
    """27.0 -> '27', 25.75 -> '25.75'."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _program_label(candidate: CandidateProgram) -> str:
    """Tên ngành hiển thị: program_name_raw (tên thực của trường) ưu tiên,
    fallback program_name (canonical) khi raw rỗng/null."""
    raw = (candidate.program_name_raw or "").strip()
    return raw or candidate.program_name


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
        f"Mình đã cập nhật {label} của em từ {_fmt_num(prev)} {direction} {_fmt_num(new)}. "
        "Với dữ liệu mới, thứ tự ưu tiên thay đổi:"
    )


def _intro_paragraph(profile: StudentProfile, admission_year: Optional[int], n: int) -> str:
    facts: List[str] = []
    if admission_year:
        facts.append(f"xét tuyển năm {admission_year}")
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
            f"Dựa trên hồ sơ hiện tại của em — {', '.join(facts)} — "
            f"mình đề xuất {n} lựa chọn sau:"
        )
    return f"Dựa trên thông tin hiện có, mình đề xuất {n} lựa chọn sau:"


def _data_note(candidate: CandidateProgram, outcome_by_key: Dict[str, ResolutionOutcome]) -> Optional[str]:
    """Khối '**Lưu ý dữ liệu:**' theo từng chương trình (AC6)."""
    outcome = outcome_by_key.get(_candidate_conflict_key(candidate))
    if outcome is None and not candidate.data_uncertain_fields:
        return None

    if outcome is not None and outcome.status == "resolved" and outcome.chosen_evidence:
        field = _field_label(outcome.field_name)
        source = label_for_source(outcome.chosen_evidence.source_url)
        return (
            f"**Lưu ý dữ liệu:** Các nguồn hiện ghi khác nhau về {field}. "
            f"Hệ thống tham chiếu giá trị {outcome.resolved_value} từ {source}, "
            "nhưng em nên kiểm tra thông báo tuyển sinh chính thức mới nhất của trường trước khi đăng ký."
        )

    if outcome is not None:
        field = _field_label(outcome.field_name)
    else:
        field = ", ".join(_field_label(f) for f in candidate.data_uncertain_fields)
    return (
        f"**Lưu ý dữ liệu:** Thông tin về {field} đang mâu thuẫn giữa các nguồn. "
        "Em nên kiểm tra trực tiếp với trường trước khi đăng ký."
    )


def build_explanation(
    profile: StudentProfile,
    recommendations: List[RankedRecommendation],
    candidates: List[CandidateProgram],
    policy: Optional[PolicyDecision],
    resolution_outcomes: Optional[List[ResolutionOutcome]] = None,
    admission_year: Optional[int] = None,
    correction_note: Optional[Dict[str, Any]] = None,
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
        lines.append(_intro_paragraph(profile, admission_year, len(renderable)))
        for idx, (recommendation, candidate) in enumerate(renderable, start=1):
            lines.append("")
            lines.append(f"### {idx}. {candidate.school_name} — {_program_label(candidate)}")
            lines.append("")
            lines.append(f"**Mức phù hợp: {BAND_FIT_LABELS.get(recommendation.band, recommendation.band)}**")

            bullets = [_translate(r) for r in recommendation.reasons[:3]]
            bullets += [_translate(c) for c in recommendation.cautions[:3]]
            if bullets:
                lines.append("")
                for bullet in bullets:
                    lines.append(f"- {bullet}")

            note = _data_note(candidate, outcome_by_key)
            if note:
                lines.append("")
                lines.append(note)
    else:
        lines.append("Chưa có đề xuất phù hợp từ dữ liệu hiện tại.")

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

    if renderable:
        lines.append("")
        lines.append(CLOSING_QUESTION)

    return "\n".join(lines)
