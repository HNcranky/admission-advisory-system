from agents.models import CandidateProgram
from services.conflict.models import EvidenceOption, ResolutionOutcome
from state import AgentState


def test_agent_state_has_conflict_record_and_resolution_outcome_lists():
    state = AgentState(user_query="Tu van CNTT")

    assert state.conflict_records == []
    assert state.resolution_outcomes == []


def test_candidate_program_has_data_uncertain_fields():
    candidate = CandidateProgram(
        candidate_id="vnu_uet:2026:cntt:thpt_score",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
    )

    assert candidate.data_uncertain_fields == []


def test_state_accepts_resolution_outcomes():
    option = EvidenceOption(evidence_id="mock://x|quota", source_url="mock://x", value=150)
    outcome = ResolutionOutcome(
        conflict_key="vnu_uet:2026:cntt:thpt_score",
        field_name="quota",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        program_name="Cong nghe thong tin",
        status="resolved",
        resolved_value=150,
        chosen_evidence=option,
        rationale="Higher trust source.",
    )
    state = AgentState(user_query="Tu van CNTT", resolution_outcomes=[outcome])

    assert state.resolution_outcomes[0].resolved_value == 150
