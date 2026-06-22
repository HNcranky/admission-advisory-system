# tests/services/chat/test_turn_routing_characterization.py
from unittest.mock import MagicMock

import pytest

from services.chat.conversation_service import ConversationService
from services.chat.intent_router import IntentResult
from services.chat.models import ChatProfileState, FlowState


def _svc(route_result, profile=None, flow=None, session_status="collecting_profile"):
    repo = MagicMock()
    repo.list_message.return_value = []
    repo.get_profile_state.return_value = profile or ChatProfileState()
    repo.get_flow_state.return_value = flow or FlowState()
    session = MagicMock(status=session_status, latest_run_id=None)
    repo.get_session_by_token.return_value = session
    repo.count_runs.return_value = 0
    svc = ConversationService(
        repository=repo,
        extract_profile=lambda *a, **k: {},
        intent_router=MagicMock(),
        knowledge_qa=MagicMock(),
    )
    svc.intent_router.classify.return_value = route_result
    return svc, repo


def test_conversational_route_returns_greeting_no_run():
    svc, repo = _svc(IntentResult(route="CONVERSATIONAL", subtype="GREETING"))
    result = svc.handle_user_message("tok", "xin chào")
    assert result.should_start_run is False
    assert result.assistant_message  # non-empty greeting
    # an assistant message was persisted
    assert any(c.args[1] == "assistant" for c in repo.append_message.call_args_list)


def test_out_of_scope_route():
    svc, repo = _svc(IntentResult(route="OUT_OF_SCOPE"))
    result = svc.handle_user_message("tok", "thời tiết hôm nay")
    assert result.should_start_run is False
    assert "ngoài phạm vi" in result.assistant_message.lower()


def test_clarification_route_uses_missing_field_prompt():
    svc, repo = _svc(IntentResult(route="CLARIFICATION", missing_fields=["school"]))
    result = svc.handle_user_message("tok", "thế còn cái đó")
    assert result.should_start_run is False
    assert "trường nào" in result.assistant_message.lower()


def test_knowledge_qa_route_calls_service_and_formats_answer():
    svc, repo = _svc(IntentResult(route="KNOWLEDGE_QA", topic="tuition", school="UET"))
    answer = MagicMock(has_data=True, answer="Học phí 15tr.", citations=[])
    svc.knowledge_qa.answer.return_value = answer
    result = svc.handle_user_message("tok", "học phí UET?")
    assert result.should_start_run is False
    assert "Học phí 15tr." in result.assistant_message
    svc.knowledge_qa.answer.assert_called_once()


def test_hybrid_route_complete_profile_starts_hybrid_run():
    full = ChatProfileState(total_score=25, admission_method="thpt_score",
                            subject_combination="A00", admission_year=2026,
                            preferred_schools=["UET"], preferred_majors=["CNTT"])
    svc, repo = _svc(IntentResult(route="HYBRID", schools=["UET", "HUST"], topics=["tuition"],
                                  needs_advisory=True),
                     profile=full, session_status="ready")
    result = svc.handle_user_message("tok", "so sánh điểm chuẩn lẫn học phí UET HUST")
    assert result.should_start_run is True
    assert result.run_kind == "hybrid"
    assert result.hybrid_intent is not None


def test_advisory_route_incomplete_profile_asks_follow_up():
    svc, repo = _svc(IntentResult(route="ADVISORY_FLOW"),
                     profile=ChatProfileState(), flow=FlowState())
    result = svc.handle_user_message("tok", "tư vấn ngành CNTT")
    assert result.should_start_run is False
    assert result.assistant_message  # a follow-up question
    assert result.session_status == "collecting_profile"


def test_reset_route_starts_fresh_profile():
    svc, repo = _svc(IntentResult(route="RESET_PROFILE"))
    # Note: explicit reset phrases are caught pre-intent; this drives the router branch.
    result = svc.handle_user_message("tok", "tư vấn cho em gái mình")
    assert result.should_start_run is False
    assert result.profile_state is not None
