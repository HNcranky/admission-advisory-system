from services.reasoning_service import reason_candidates
from state import AgentState


def reasoning_agent(state: AgentState):
    checks, recommendations = reason_candidates(
        profile=state.student_profile,
        candidates=state.retrieved_programs,
    )
    state.eligibility_checks = checks
    state.ranked_recommendations = recommendations
    return state
