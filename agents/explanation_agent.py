from services.explanation_service import build_explanation
from state import AgentState


def explanation_agent(state: AgentState):
    state.final_answer = build_explanation(
        profile=state.student_profile,
        recommendations=state.ranked_recommendations,
        candidates=state.retrieved_programs,
        policy=state.policy_decision,
        resolution_outcomes=state.resolution_outcomes,
    )
    state.advisory = state.final_answer
    state.citations = [ev for program in state.retrieved_programs for ev in program.evidence]
    return state
