import contextlib
from unittest.mock import MagicMock

from services.chat import conversation_service as cs_mod
from services.chat.conversation_service import ConversationService
from services.chat.models import ChatProfileState, ConversationTurnResult, FlowState


def _service_with_stubs(monkeypatch):
    svc = ConversationService(
        repository=MagicMock(),
        extract_profile=lambda *a, **k: {},
        intent_router=MagicMock(),
        knowledge_qa=MagicMock(),
    )
    repo = svc.repository
    repo.list_message.return_value = []
    repo.get_session_by_token.return_value = None
    repo.get_profile_state.return_value = ChatProfileState()
    repo.get_flow_state.return_value = FlowState()
    svc.intent_router.classify.return_value = MagicMock(route="CONVERSATIONAL", subtype="GREETING")
    return svc


def test_handle_user_message_opens_turn_trace(monkeypatch):
    opened = []

    @contextlib.contextmanager
    def fake_turn_trace(turn_id, session_token, user_message):
        opened.append((turn_id, session_token, user_message))
        yield None

    monkeypatch.setattr(cs_mod, "turn_trace", fake_turn_trace)
    svc = _service_with_stubs(monkeypatch)

    result = svc.handle_user_message("tok", "xin chào")

    assert isinstance(result, ConversationTurnResult)
    assert len(opened) == 1
    assert opened[0][1] == "tok" and opened[0][2] == "xin chào"
