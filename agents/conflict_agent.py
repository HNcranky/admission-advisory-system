from services import build_default_gateway
from services.conflict.comparison_agent import compare
from services.conflict.detection import detect_cutoff_conflicts, detect_quota_conflicts
from services.conflict.evidence_agent import package_evidence
from services.conflict.resolution_agent import resolve, resolve_cutoff_conflict
from services.conflict.resolution_inference_service import batch_interpret_conflict_tiebreak
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

    # Gateway (LLM tiebreaker) CHỈ cho quota; cutoff không bao giờ pick-winner bằng LLM (EC-16).
    gateway = build_default_gateway() if quota_records else None

    # Pha A: dựng (record, report) cho mọi quota conflict.
    pairs = []
    for record in quota_records:
        options = package_evidence(record, state.retrieved_programs)
        record.options = options
        report = compare(options)
        pairs.append((record, report))

    # Pha B: chỉ conflict indecisive cần LLM → MỘT call gom cả batch.
    indecisive = [(record, report) for record, report in pairs if not report.is_decisive]
    decisions = (
        batch_interpret_conflict_tiebreak(indecisive, gateway)
        if gateway is not None else {}
    )

    def _lookup(record, report):
        return decisions.get(record.conflict_key, {"confidence": "low"})

    tiebreak = _lookup if gateway is not None else None

    # Pha C: resolve() KHÔNG đổi — nhận callback tra cứu thay vì callback LLM.
    for record, report in pairs:
        outcome = resolve(record, report, gateway=tiebreak)
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
        outcome.rationale
        for outcome in outcomes
        if outcome.status == "unresolved" or outcome.used_llm_tiebreaker
    ]
    return state
