from typing import Optional

from services.conflict.models import ComparisonReport, ConflictRecord, EvidenceOption, ResolutionOutcome
from services.cutoff.assessment import classify_margin
from services.profile.admission_methods import THANG_30_METHODS


def _unresolved(record: ConflictRecord, reason: str) -> ResolutionOutcome:
    return ResolutionOutcome(
        conflict_key=record.conflict_key,
        field_name=record.field_name,
        school_id=record.school_id,
        school_name=record.school_name,
        program_name=record.program_name,
        status="unresolved",
        rationale=reason,
        uncertainty_reason=reason,
    )


def resolve(record: ConflictRecord, report: ComparisonReport) -> ResolutionOutcome:
    """Pure-deterministic resolution. A decisive comparison resolves to its
    top-ranked option; an all-axes tie is left unresolved (the caller marks the
    field uncertain and the advisory surfaces every value). No LLM call."""
    if report.is_decisive and report.ranked_options:
        chosen = report.ranked_options[0]
        return ResolutionOutcome(
            conflict_key=record.conflict_key,
            field_name=record.field_name,
            school_id=record.school_id,
            school_name=record.school_name,
            program_name=record.program_name,
            status="resolved",
            resolved_value=chosen.value,
            chosen_evidence=chosen,
            rejected_evidence=report.ranked_options[1:],
            rationale="Resolved by deterministic comparison.",
            decision_axes=report.decision_axes,
        )
    return _unresolved(record, "Comparison was not decisive.")


def _fmt_value(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def resolve_cutoff_conflict(record: ConflictRecord, profile) -> ResolutionOutcome:
    """EC-16: cutoff KHÔNG BAO GIỜ qua LLM pick-winner.

    Decision-changing (các giá trị cho nhãn khác nhau với điểm hồ sơ) → unresolved
    (caller mark uncertain + explanation hiển thị đủ giá trị). Ngược lại (cùng nhãn,
    hoặc thiếu điểm/phương thức để phân loại) → resolved theo nguồn trust cao nhất,
    rationale luôn nêu đủ các giá trị.
    """
    options = sorted(
        record.options,
        key=lambda o: (
            -(o.trust_level if o.trust_level is not None else -1),
            -(o.value if isinstance(o.value, (int, float)) else 0),
        ),
    )
    values_text = " / ".join(_fmt_value(o.value) for o in options)

    total_score = getattr(profile, "total_score", None)
    method = getattr(profile, "admission_method", None)
    decision_changing = False
    if total_score is not None and method in THANG_30_METHODS:
        fits = {
            classify_margin(total_score, o.value)
            for o in options
            if isinstance(o.value, (int, float))
        }
        decision_changing = len(fits) > 1

    if decision_changing:
        reason = (
            f"Kết luận thay đổi theo nguồn: các nguồn ghi {values_text} cho điểm chuẩn "
            f"tham chiếu {record.admission_year} của {record.program_name}."
        )
        outcome = _unresolved(record, reason)
        outcome.rejected_evidence = options
        return outcome

    chosen = options[0]
    return ResolutionOutcome(
        conflict_key=record.conflict_key,
        field_name=record.field_name,
        school_id=record.school_id,
        school_name=record.school_name,
        program_name=record.program_name,
        status="resolved",
        resolved_value=chosen.value,
        chosen_evidence=chosen,
        rejected_evidence=options[1:],
        rationale=(
            f"Các nguồn ghi khác nhau ({values_text}); hệ thống tham chiếu giá trị "
            f"{_fmt_value(chosen.value)} từ nguồn tin cậy cao nhất."
        ),
        decision_axes=["trust_level"],
    )
