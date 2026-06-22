from services.conflict.comparison import compare
from services.conflict.detection import detect_cutoff_conflicts, detect_quota_conflicts
from services.conflict.evidence import package_evidence
from services.conflict.keys import quota_key_text
from services.conflict.resolution import resolve, resolve_cutoff_conflict
from state import AgentState


def _mark_uncertain(state: AgentState, conflict_key: str, field_name: str) -> None:
    for candidate in state.retrieved_programs:
        if quota_key_text(candidate) == conflict_key and field_name not in candidate.data_uncertain_fields:
            candidate.data_uncertain_fields.append(field_name)


def _mark_uncertain_cutoff(state: AgentState, school_id: str, program_key: str) -> None:
    """conflict_key của cutoff chứa cutoff_year (≠ admission_year của candidate)
    nên không match key candidate — mark theo (school, program)."""
    for candidate in state.retrieved_programs:
        if candidate.school_id != school_id:
            continue
        if (candidate.program_id or candidate.program_name) != program_key:
            continue
        if "cutoff_score" not in candidate.data_uncertain_fields:
            candidate.data_uncertain_fields.append("cutoff_score")


def conflict_agent(state: AgentState):
    quota_records = detect_quota_conflicts(state.retrieved_programs)
    cutoff_records = detect_cutoff_conflicts(state.retrieved_programs)
    outcomes = []

    # Quota conflicts: build evidence, compare, resolve deterministically.
    # An all-axes tie resolves to `unresolved` (no LLM tiebreak).
    for record in quota_records:
        options = package_evidence(record, state.retrieved_programs)
        record.options = options
        report = compare(options)
        outcome = resolve(record, report)
        outcomes.append(outcome)
        if outcome.status == "unresolved":
            _mark_uncertain(state, record.conflict_key, record.field_name)

    for record in cutoff_records:
        outcome = resolve_cutoff_conflict(record, state.student_profile)
        outcomes.append(outcome)
        if outcome.status == "unresolved":
            _mark_uncertain_cutoff(
                state, record.school_id, record.program_id or record.program_name
            )

    state.conflict_records = quota_records + cutoff_records
    state.resolution_outcomes = outcomes
    state.conflicts = [
        outcome.rationale for outcome in outcomes if outcome.status == "unresolved"
    ]
    return state
