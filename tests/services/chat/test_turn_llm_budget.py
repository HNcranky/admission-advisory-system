from types import SimpleNamespace

from services.chat.conversation_service import ConversationService
from services.chat.models import ChatProfileState, FlowState
from services.chat.intent_router import IntentResult


class _Repo:
    def __init__(self):
        self.profile_state = ChatProfileState()
        self.flow_state = FlowState(active_flow="ADVISORY_FLOW",
                                    pending_question="Bạn đang xét tuyển cho năm nào?")
        self.status = "collecting_profile"
        self.messages = []

    def append_message(self, *a):
        self.messages.append(a)

    def list_message(self, t):
        return []

    def get_session_by_token(self, t):
        return SimpleNamespace(status=self.status)

    def get_profile_state(self, t):
        return self.profile_state

    def update_profile_state(self, t, p, s):
        self.profile_state = p
        self.status = s

    def get_flow_state(self, t):
        return self.flow_state

    def update_flow_state(self, t, f):
        self.flow_state = f


class _CountingRouter:
    def __init__(self):
        self.calls = 0

    def classify(self, message, profile_state, history=""):
        self.calls += 1
        return IntentResult(route="ADVISORY_FLOW")


def test_side_question_turn_extract_once_classify_once():
    extract_calls = {"n": 0}

    def extract(text, known_state=None, active_slot=None):
        extract_calls["n"] += 1
        return {}

    router = _CountingRouter()
    service = ConversationService(repository=_Repo(), extract_profile=extract, intent_router=router)
    service.handle_user_message("tok", "câu không điền slot")
    assert extract_calls["n"] == 1   # trước slice 3 có thể là 2
    assert router.calls == 1
