# tests/services/chat/test_turn_graph.py
from services.chat.models import ChatProfileState, FlowState


def test_turn_state_defaults():
    from services.chat.turn_graph import TurnState
    st = TurnState(session_token="tok", content="hi",
                   profile_state=ChatProfileState(), flow_state=FlowState(), delta={})
    assert st.route is None and st.result is None and st.session_status == "collecting_profile"


from unittest.mock import MagicMock

from services.chat.intent_router import IntentResult
from services.chat.models import ConversationTurnResult


def _fake_service():
    svc = MagicMock()
    def _result(msg="ok", run=False):
        return ConversationTurnResult(session_status="collecting_profile",
                                      assistant_message=msg, should_start_run=run,
                                      profile_state=ChatProfileState())
    svc._handle_knowledge_qa.return_value = _result("kqa")
    svc._handle_conversational.return_value = _result("conv")
    svc._handle_clarification.return_value = _result("clar")
    # guards (run before classify) must pass through for routing tests
    svc._maybe_continue_advisory.return_value = None
    svc._maybe_correction_rerun.return_value = None
    return svc


def _state(route, **kw):
    return dict(session_token="tok", content="x", profile_state=ChatProfileState(),
                flow_state=FlowState(), delta={}, intent=IntentResult(route=route),
                **kw)


def test_turn_graph_routes_knowledge_qa():
    from services.chat.turn_graph import TurnState, build_turn_graph
    svc = _fake_service()
    svc.intent_router.classify.return_value = IntentResult(route="KNOWLEDGE_QA", topic="tuition")
    graph = build_turn_graph(svc)
    final = graph.invoke(TurnState(session_token="tok", content="học phí?",
                                   profile_state=ChatProfileState(), flow_state=FlowState(), delta={}))
    result = final["result"] if isinstance(final, dict) else final.result
    assert result.assistant_message == "kqa"
    svc._handle_knowledge_qa.assert_called_once()


def test_turn_graph_unknown_route_falls_to_clarification():
    from services.chat.turn_graph import TurnState, build_turn_graph
    svc = _fake_service()
    svc.intent_router.classify.return_value = IntentResult(route="CLARIFICATION", missing_fields=[])
    graph = build_turn_graph(svc)
    final = graph.invoke(TurnState(session_token="tok", content="?",
                                   profile_state=ChatProfileState(), flow_state=FlowState(), delta={}))
    result = final["result"] if isinstance(final, dict) else final.result
    assert result.assistant_message == "clar"
    svc._handle_clarification.assert_called_once()


def test_guard_short_circuits_before_classify():
    from services.chat.turn_graph import TurnState, build_turn_graph
    from services.chat.models import ChatProfileState, ConversationTurnResult, FlowState
    from unittest.mock import MagicMock
    svc = MagicMock()
    svc._maybe_continue_advisory.return_value = ConversationTurnResult(
        session_status="collecting_profile", assistant_message="continued",
        profile_state=ChatProfileState())
    svc._maybe_correction_rerun.return_value = None
    graph = build_turn_graph(svc)
    final = graph.invoke(TurnState(session_token="tok", content="năm 2026",
                                   profile_state=ChatProfileState(),
                                   flow_state=FlowState(active_flow="ADVISORY_FLOW",
                                                        pending_question="năm nào?"),
                                   delta={"admission_year": 2026}))
    result = final["result"] if isinstance(final, dict) else final.result
    assert result.assistant_message == "continued"
    svc.intent_router.classify.assert_not_called()  # classify skipped
