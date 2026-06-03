from types import SimpleNamespace

from fastapi.testclient import TestClient

from services.chat.conversation_service import ConversationService
from services.chat.models import ChatProfileState, ConversationTurnResult, ChatMessageRecord, ChatSessionSnapshot, FlowState
from web.app import build_app


def test_post_message_returns_follow_up_payload(monkeypatch):
    client = TestClient(build_app())

    class FakeService:
        def handle_user_message(self, session_token, content):
            assert session_token == "session-123"
            assert content == "Em muon hoc CNTT"
            return ConversationTurnResult(
                session_status="collecting_profile",
                assistant_message="Tổng điểm hoặc mức điểm ước tính của bạn là bao nhiêu?",
                should_start_run=False,
                profile_state=ChatProfileState(
                    admission_year=2026,
                    preferred_majors=["computer_science"],
                    location_preference="Ha Noi",
                    missing_slots=["total_score"],
                ),
            )

    monkeypatch.setattr("web.routes.chat_api.get_conversation_service", lambda: FakeService())

    response = client.post(
        "/api/sessions/session-123/messages",
        json={"content": "Em muon hoc CNTT"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_status"] == "collecting_profile"
    assert body["should_start_run"] is False
    assert body["profile_state"]["missing_slots"] == ["total_score"]


def test_post_message_returns_ready_payload(monkeypatch):
    client = TestClient(build_app())

    class FakeRepository:
        def create_run(self, session_token, profile_state):
            return 7

    class FakeService:
        def __init__(self):
            self.repository = FakeRepository()

        def handle_user_message(self, session_token, content):
            return ConversationTurnResult(
                session_status="ready",
                assistant_message="Cảm ơn bạn. Mình đã có đủ thông tin và sẽ bắt đầu phân tích.",
                should_start_run=True,
                profile_state=ChatProfileState(
                    admission_year=2026,
                    total_score=27.0,
                    preferred_majors=["computer_science"],
                    location_preference="Ha Noi",
                    missing_slots=[],
                ),
            )

    class FakeDispatcher:
        def submit(self, session_token, run_id, latest_user_message, profile_state, correction_note=None):
            return None

    monkeypatch.setattr("web.routes.chat_api.get_conversation_service", lambda: FakeService())
    monkeypatch.setattr("web.routes.chat_api.get_run_dispatcher", lambda: FakeDispatcher())

    response = client.post(
        "/api/sessions/session-123/messages",
        json={"content": "Em muon hoc CNTT tai Ha Noi nam 2026 va duoc 27 diem"},
    )

    assert response.status_code == 200
    assert response.json()["should_start_run"] is True


def test_post_message_uses_fallback_extractor_when_gateway_is_unavailable(monkeypatch):
    client = TestClient(build_app())

    class FakeRepository:
        def __init__(self):
            self.profile_state = ChatProfileState()
            self.flow_state = FlowState()
            self.messages = []
            self.status = "collecting_profile"

        def append_message(self, session_token, role, content, kind="chat"):
            self.messages.append((role, kind, content))

        def get_session_by_token(self, session_token):
            return SimpleNamespace(session_token=session_token, status=self.status)

        def get_profile_state(self, session_token):
            return self.profile_state

        def update_profile_state(self, session_token, profile_state, status):
            self.profile_state = profile_state
            self.status = status
            return profile_state

        def get_flow_state(self, session_token):
            return self.flow_state

        def update_flow_state(self, session_token, flow_state):
            self.flow_state = flow_state

    class UnavailableGateway:
        def is_available(self):
            return False

        def run(self, request):
            raise AssertionError("gateway.run should not be called when unavailable")

    monkeypatch.setattr(
        "services.chat.conversation_service.build_default_gateway",
        lambda: UnavailableGateway(),
    )
    # Also patch the intent router's gateway so it falls back to ADVISORY_FLOW
    # without making network calls.
    monkeypatch.setattr(
        "services.chat.intent_router.build_default_gateway",
        lambda: UnavailableGateway(),
    )
    monkeypatch.setattr(
        "web.routes.chat_api.get_conversation_service",
        lambda: ConversationService(repository=FakeRepository()),
    )

    response = client.post(
        "/api/sessions/session-123/messages",
        json={"content": "Em muon hoc CNTT tai HUST nam 2026"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_status"] == "collecting_profile"
    assert body["should_start_run"] is False
    assert body["profile_state"]["preferred_majors"] == ["computer_science"]
    # preferred_schools is LLM-opportunistic (spec §5/§9): with the gateway
    # unavailable the DST extractor only yields the deterministic delta
    # (active-slot parse + tiered major resolver), so no school is captured.
    assert body["profile_state"]["preferred_schools"] == []
    assert body["profile_state"]["missing_slots"] == ["total_score", "subject_combination"]
    
    
def test_create_session_endpoint_returns_snapshot(monkeypatch):
    client = TestClient(build_app())

    class FakeSessionService:
        def start_session(self):
            return ChatSessionSnapshot(
                session={
                    "id": 1,
                    "session_token": "session-123",
                    "status": "collecting_profile",
                    "profile_state_json": {},
                    "latest_run_id": None,
                },
                messages=[
                    ChatMessageRecord(
                        id=1,
                        session_token="session-123",
                        role="assistant",
                        kind="assistant_welcome",
                        content="Chào bạn",
                    )
                ],
            )

    monkeypatch.setattr("web.routes.chat_api.get_session_service", lambda: FakeSessionService())

    response = client.post("/api/sessions")

    assert response.status_code == 201
    body = response.json()
    assert body["session"]["session_token"] == "session-123"
    assert body["messages"][0]["kind"] == "assistant_welcome"


def test_post_message_dispatches_hybrid_run(monkeypatch):
    from services.chat.models import ConversationTurnResult

    client = TestClient(build_app())

    class FakeRepository:
        def create_run(self, session_token, profile_state):
            return 55

    class FakeService:
        def __init__(self):
            self.repository = FakeRepository()

        def handle_user_message(self, session_token, content):
            return ConversationTurnResult(
                session_status="running",
                assistant_message="đang tổng hợp",
                should_start_run=True,
                run_kind="hybrid",
                hybrid_intent={"route": "HYBRID", "schools": ["VNU-UET", "HUST"],
                               "topics": ["tuition"], "needs_advisory": True},
                profile_state=ChatProfileState(
                    admission_year=2026, total_score=27.0,
                    preferred_majors=["computer_science"], location_preference="Ha Noi",
                ),
            )

    captured = {}

    class FakeHybridDispatcher:
        def submit(self, session_token, run_id, content, profile_state, intent):
            captured["run_id"] = run_id
            captured["intent_schools"] = intent.schools
            captured["content"] = content

    class FailRunDispatcher:
        def submit(self, **kwargs):
            raise AssertionError("advisory dispatcher must not be used for a hybrid run")

    monkeypatch.setattr("web.routes.chat_api.get_conversation_service", lambda: FakeService())
    monkeypatch.setattr("web.routes.chat_api.get_hybrid_dispatcher", lambda: FakeHybridDispatcher())
    monkeypatch.setattr("web.routes.chat_api.get_run_dispatcher", lambda: FailRunDispatcher())

    response = client.post("/api/sessions/s/messages", json={"content": "so sánh UET và HUST"})

    assert response.status_code == 200
    assert response.json()["run_kind"] == "hybrid"
    assert captured["run_id"] == 55
    assert captured["intent_schools"] == ["VNU-UET", "HUST"]
    assert captured["content"] == "so sánh UET và HUST"


def test_get_session_endpoint_returns_404_when_missing(monkeypatch):
    client = TestClient(build_app())

    class FakeSessionService:
        def get_session_snapshot(self, session_token):
            return ChatSessionSnapshot(session=None, messages=[])

    monkeypatch.setattr("web.routes.chat_api.get_session_service", lambda: FakeSessionService())

    response = client.get("/api/sessions/missing-token")

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"
