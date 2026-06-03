from services.retrieval_service import (
    build_retrieval_filters,
    fetch_candidates,
)
from state import AgentState


def retrieval_agent(state: AgentState):
    filters = build_retrieval_filters(state.student_profile, state.admission_year)
    state.retrieval_filters = filters

    try:
        candidates = fetch_candidates(filters=filters)
    except Exception as exc:
        state.retrieved_programs = []
        state.conflicts = [f"Retrieval error: {exc}"]
        return state

    subject_combination = state.student_profile.subject_combination
    if subject_combination:
        candidates = [
            candidate
            for candidate in candidates
            if not candidate.subject_combinations
            or subject_combination in candidate.subject_combinations
        ]

    state.retrieved_programs = candidates
    return state
