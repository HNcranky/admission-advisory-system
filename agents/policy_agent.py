from services import build_default_gateway
from services.policy_inference_service import interpret_policy_ambiguity
from services.policy_service import evaluate_policy_guardrails
from state import AgentState


def policy_agent(state: AgentState):
    decision, filtered_recommendations = evaluate_policy_guardrails(
        user_query=state.user_query,
        profile=state.student_profile,
        candidates=state.retrieved_programs,
        recommendations=state.ranked_recommendations,
        conflicts=state.conflicts,
    )

    if state.conflicts:
        gateway = build_default_gateway()
        ambiguity = interpret_policy_ambiguity(state.user_query, state.conflicts, gateway)
        decision.warnings.extend(ambiguity["warnings"])
        if ambiguity["requires_human_verification"]:
            state.uncertainty_reasons.append("policy_ambiguity_requires_verification")

    state.policy_decision = decision
    state.ranked_recommendations = filtered_recommendations
    return state