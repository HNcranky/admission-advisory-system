from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState, ConversationTurnResult, FlowState


class TurnState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_token: str
    content: str
    history_ctx: str = ""
    prev_user: str = ""
    profile_state: ChatProfileState
    flow_state: FlowState
    delta: dict = Field(default_factory=dict)
    session_status: str = "collecting_profile"
    session: Any = None

    intent: Optional[IntentResult] = None
    route: Optional[str] = None
    result: Optional[ConversationTurnResult] = None


from langgraph.graph import END, StateGraph

_ROUTE_TO_NODE = {
    "ADVISORY_FLOW": "advisory",
    "KNOWLEDGE_QA": "knowledge_qa",
    "HYBRID": "hybrid",
    "FOLLOWUP": "followup",
    "OUT_OF_SCOPE": "out_of_scope",
    "CONVERSATIONAL": "conversational",
    "RESET_PROFILE": "reset",
}


def build_turn_graph(service):
    """Compile: classify → (conditional by route) → one handler node → END.
    Handler nodes wrap the existing ConversationService._handle_* methods, so
    behaviour mirrors the former inline if/elif block (conversation_service.py)."""

    from services.profile.validation import validate_profile_delta

    def reset_guard(state: TurnState) -> TurnState:
        from services.chat.conversation_service import _is_reset_request
        if _is_reset_request(state.content):
            state.result = service._handle_reset(state.session_token, state.delta, state.flow_state)
        return state

    def rejection_guard(state: TurnState) -> TurnState:
        clean_delta, rejections = validate_profile_delta(state.delta, state.profile_state)
        state.delta = clean_delta
        if rejections:
            state.result = service._handle_rejection(
                state.session_token, state.profile_state, state.flow_state, clean_delta, rejections)
        return state

    def continue_guard(state: TurnState) -> TurnState:
        r = service._maybe_continue_advisory(
            state.session_token, state.content, state.profile_state, state.flow_state, state.delta)
        if r is not None:
            state.result = r
        return state

    def correction_guard(state: TurnState) -> TurnState:
        r = service._maybe_correction_rerun(
            state.session_token, state.profile_state, state.flow_state, state.delta, state.session)
        if r is not None:
            state.result = r
        return state

    def _guard_gate(next_node):
        def gate(state: TurnState) -> str:
            return "end" if state.result is not None else next_node
        return gate

    def classify(state: TurnState) -> TurnState:
        if state.intent is None:
            state.intent = service.intent_router.classify(
                state.content, state.profile_state, history=state.history_ctx
            )
        state.route = state.intent.route
        return state

    def advisory(state: TurnState) -> TurnState:
        state.result = service._handle_advisory(
            state.session_token, state.profile_state, state.flow_state, state.delta)
        return state

    def knowledge_qa(state: TurnState) -> TurnState:
        state.result = service._handle_knowledge_qa(
            state.session_token, state.content, state.intent, state.profile_state,
            state.flow_state, state.session_status, state.history_ctx, state.prev_user)
        return state

    def followup(state: TurnState) -> TurnState:
        state.result = service._handle_followup(
            state.session_token, state.content, state.intent, state.profile_state,
            state.flow_state, state.session_status, state.history_ctx, state.prev_user)
        return state

    def hybrid(state: TurnState) -> TurnState:
        state.result = service._handle_hybrid(
            state.session_token, state.content, state.intent, state.profile_state,
            state.flow_state, state.session_status, state.history_ctx, state.prev_user)
        return state

    def out_of_scope(state: TurnState) -> TurnState:
        state.result = service._handle_out_of_scope(
            state.session_token, state.profile_state, state.flow_state, state.session_status)
        return state

    def conversational(state: TurnState) -> TurnState:
        state.result = service._handle_conversational(
            state.session_token, state.content, state.intent, state.profile_state,
            state.flow_state, state.session_status)
        return state

    def reset(state: TurnState) -> TurnState:
        state.result = service._handle_reset(state.session_token, state.delta, state.flow_state)
        return state

    def clarification(state: TurnState) -> TurnState:
        state.result = service._handle_clarification(
            state.session_token, state.intent, state.profile_state, state.flow_state,
            state.session_status)
        return state

    def route_selector(state: TurnState) -> str:
        return _ROUTE_TO_NODE.get(state.route, "clarification")

    builder = StateGraph(TurnState)
    for name, fn in [
        ("classify", classify), ("advisory", advisory), ("knowledge_qa", knowledge_qa),
        ("followup", followup),
        ("hybrid", hybrid), ("out_of_scope", out_of_scope), ("conversational", conversational),
        ("reset", reset), ("clarification", clarification),
    ]:
        builder.add_node(name, fn)

    builder.add_node("reset_guard", reset_guard)
    builder.add_node("rejection_guard", rejection_guard)
    builder.add_node("continue_guard", continue_guard)
    builder.add_node("correction_guard", correction_guard)

    builder.set_entry_point("reset_guard")
    builder.add_conditional_edges("reset_guard", _guard_gate("rejection_guard"),
                                  {"end": END, "rejection_guard": "rejection_guard"})
    builder.add_conditional_edges("rejection_guard", _guard_gate("continue_guard"),
                                  {"end": END, "continue_guard": "continue_guard"})
    builder.add_conditional_edges("continue_guard", _guard_gate("correction_guard"),
                                  {"end": END, "correction_guard": "correction_guard"})
    builder.add_conditional_edges("correction_guard", _guard_gate("classify"),
                                  {"end": END, "classify": "classify"})
    builder.add_conditional_edges("classify", route_selector, {
        "advisory": "advisory", "knowledge_qa": "knowledge_qa", "hybrid": "hybrid",
        "followup": "followup",
        "out_of_scope": "out_of_scope", "conversational": "conversational",
        "reset": "reset", "clarification": "clarification",
    })
    for name in ["advisory", "knowledge_qa", "followup", "hybrid", "out_of_scope",
                 "conversational", "reset", "clarification"]:
        builder.add_edge(name, END)
    return builder.compile()
