from services import build_default_gateway
from services.conflict.comparison_agent import compare
from services.conflict.detection import detect_quota_conflicts
from services.conflict.evidence_agent import package_evidence
from services.conflict.resolution_agent import resolve
from services.conflict.resolution_inference_service import interpret_conflict_tiebreak
from state import AgentState


def _mark_uncertain(state: AgentState, conflict_key: str, field_name: str) -> None:
    for candidate in state.retrieved_programs:
        key = ":".join(
            [
                candidate.school_id,
                str(candidate.admission_year),
                candidate.program_id or candidate.program_name,
                candidate.admission_method or "unknown_method",
            ]
        )
        if key == conflict_key and field_name not in candidate.data_uncertain_fields:
            candidate.data_uncertain_fields.append(field_name)


def conflict_agent(state: AgentState):
    records = detect_quota_conflicts(state.retrieved_programs)
    outcomes = []

    gateway = build_default_gateway() if records else None
    tiebreak = (
        (lambda record, report: interpret_conflict_tiebreak(record, report, gateway))
        if gateway is not None
        else None
    )

    for record in records:
        options = package_evidence(record, state.retrieved_programs)
        record.options = options
        report = compare(options)
        outcome = resolve(record, report, gateway=tiebreak)
        outcomes.append(outcome)
        if outcome.status == "unresolved":
            _mark_uncertain(state, record.conflict_key, record.field_name)

    state.conflict_records = records
    state.resolution_outcomes = outcomes
    state.conflicts = [
        outcome.rationale
        for outcome in outcomes
        if outcome.status == "unresolved" or outcome.used_llm_tiebreaker
    ]
    return state
