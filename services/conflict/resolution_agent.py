from typing import Callable, Optional

from services.conflict.models import ComparisonReport, ConflictRecord, EvidenceOption, ResolutionOutcome

GatewayFunc = Callable[..., dict]


def _unresolved(record: ConflictRecord, reason: str, used_llm: bool = False) -> ResolutionOutcome:
    return ResolutionOutcome(
        conflict_key=record.conflict_key,
        field_name=record.field_name,
        school_id=record.school_id,
        school_name=record.school_name,
        program_name=record.program_name,
        status="unresolved",
        rationale=reason,
        uncertainty_reason=reason,
        used_llm_tiebreaker=used_llm,
    )


def _find_option(report: ComparisonReport, source_url: str) -> Optional[EvidenceOption]:
    for option in report.ranked_options:
        if option.source_url == source_url:
            return option
    return None


def resolve(
    record: ConflictRecord,
    report: ComparisonReport,
    gateway: Optional[GatewayFunc] = None,
) -> ResolutionOutcome:
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

    if gateway is None:
        return _unresolved(record, "Comparison was not decisive.")

    try:
        response = gateway(record=record, report=report)
    except Exception:
        return _unresolved(record, "LLM tiebreaker failed.", used_llm=True)

    if response.get("confidence") != "high":
        return _unresolved(record, "LLM tiebreaker did not reach high confidence.", used_llm=True)

    chosen = _find_option(report, response.get("chosen_source_url", ""))
    if chosen is None:
        return _unresolved(record, "LLM tiebreaker chose an unknown source.", used_llm=True)

    return ResolutionOutcome(
        conflict_key=record.conflict_key,
        field_name=record.field_name,
        school_id=record.school_id,
        school_name=record.school_name,
        program_name=record.program_name,
        status="resolved",
        resolved_value=chosen.value,
        chosen_evidence=chosen,
        rejected_evidence=[option for option in report.ranked_options if option != chosen],
        rationale=response.get("rationale") or "Resolved by LLM tiebreaker.",
        decision_axes=["llm_tiebreaker"],
        used_llm_tiebreaker=True,
    )
