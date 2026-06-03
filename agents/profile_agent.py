from services import build_default_gateway
from services.profile_inference_service import build_profile_with_gateway
from state import AgentState


def profile_agent(state: AgentState, gateway=None):
    if state.profile_seeded:
        state.retrieval_missing_data = list(state.student_profile.missing_slots)
        return state
    
    if gateway is None:
        gateway = build_default_gateway()
    state.student_profile = build_profile_with_gateway(state.user_query, gateway)
    state.retrieval_missing_data = list(state.student_profile.missing_slots)
    return state
