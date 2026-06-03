# Student Chat E2E Demo - Plan 3: Demo Hardening And Critical-Path Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the student demo path so stale local sessions recover cleanly, final recommendations are surfaced explicitly, and one complete advisory flow is covered by deterministic end-to-end tests.

**Architecture:** Build on the session API and snapshot-driven browser client from Plans 1 and 2. Add minimal startup recovery in the client, keep recommendation rendering tied to `assistant_result` messages, and add an HTTP-level smoke test with fake services so the full student flow is verified without live Gemini or background threads.

**Tech Stack:** Python, FastAPI, vanilla JavaScript, `pytest`, `fastapi.testclient`

---

## Planned File Structure

- `web/static/js/chat.js`
  - Add stale-token recovery and explicit startup error handling.
- `web/static/css/chat.css`
  - Add visual tones for pending, success, and error states plus transcript message styling.
- `tests/e2e/test_chat_web_flow.py`
  - Add regression coverage for stale-session recovery hooks.
- `tests/e2e/test_chat_session_run_flow.py`
  - Add the critical-path end-to-end API smoke test.

### Task 1: Recover Cleanly From Stale Browser Session Tokens

**Files:**
- Modify: `web/static/js/chat.js`
- Modify: `web/static/css/chat.css`
- Modify: `tests/e2e/test_chat_web_flow.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


def test_chat_client_clears_stale_session_token_and_reports_startup_errors():
    script = Path("web/static/js/chat.js").read_text(encoding="utf-8")
    styles = Path("web/static/css/chat.css").read_text(encoding="utf-8")

    assert "window.localStorage.removeItem(SESSION_KEY)" in script
    assert 'setStatus("Khong the khoi tao phien chat.", "error")' in script
    assert ".chat-status[data-tone=\"error\"]" in styles
    assert ".message--assistant" in styles
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/e2e/test_chat_web_flow.py::test_chat_client_clears_stale_session_token_and_reports_startup_errors -v`
Expected: FAIL because the Plan 2 script restores sessions but does not yet clear invalid stored tokens or expose startup error styling.

- [ ] **Step 3: Write minimal implementation**

```javascript
// web/static/js/chat.js
async function ensureSession() {
  const stored = window.localStorage.getItem(SESSION_KEY);
  if (!stored) {
    return createSession();
  }

  try {
    currentSessionToken = stored;
    return await fetchSessionSnapshot(stored);
  } catch (error) {
    window.localStorage.removeItem(SESSION_KEY);
    currentSessionToken = null;
    return createSession();
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const resetButton = document.getElementById("reset-session");

  try {
    const bootstrap = await ensureSession();
    renderSnapshot(bootstrap);
    setStatus("San sang tu van.", "info");
  } catch (error) {
    setStatus("Khong the khoi tao phien chat.", "error");
    form.querySelector("button[type='submit']").disabled = true;
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (!content) return;

    try {
      setStatus("Dang gui tin nhan...", "pending");
      const result = await sendMessage(content);
      input.value = "";

      const snapshot = await fetchSessionSnapshot(currentSessionToken);
      renderSnapshot(snapshot);

      if (result.should_start_run) {
        setStatus("Dang phan tich ho so...", "pending");
        schedulePolling(currentSessionToken);
        return;
      }

      setStatus("Da nhan cau hoi tiep theo.", "info");
    } catch (error) {
      setStatus("Khong gui duoc tin nhan.", "error");
    }
  });

  resetButton.addEventListener("click", async () => {
    stopPolling();
    window.localStorage.removeItem(SESSION_KEY);
    const snapshot = await createSession();
    renderSnapshot(snapshot);
    setStatus("Da bat dau phien chat moi.", "info");
  });
});
```

```css
/* web/static/css/chat.css */
.chat-status[data-tone="pending"] {
  color: #8a5b18;
}

.chat-status[data-tone="success"] {
  color: #24613c;
}

.chat-status[data-tone="error"] {
  color: #9f2d2d;
}

.message {
  padding: 14px 16px;
  border-radius: 16px;
  line-height: 1.5;
}

.message--assistant {
  background: #f3eee4;
}

.message--user {
  background: #dfeaf7;
  justify-self: end;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/e2e/test_chat_web_flow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/static/js/chat.js web/static/css/chat.css tests/e2e/test_chat_web_flow.py
git commit -m "feat: recover stale chat sessions in browser"
```

### Task 2: Add A Deterministic End-To-End Smoke Test For One Student Flow

**Files:**
- Modify: `tests/e2e/test_chat_session_run_flow.py`
- Modify: `web/routes/chat_api.py`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from services.chat.models import ChatMessageRecord, ChatProfileState, ChatSessionSnapshot, ConversationTurnResult
from web.app import build_app


def test_student_can_complete_follow_up_and_receive_final_result(monkeypatch):
    client = TestClient(build_app())

    session = {
        "id": 1,
        "session_token": "session-123",
        "status": "collecting_profile",
        "profile_state_json": {},
        "latest_run_id": None,
    }
    messages = [
        ChatMessageRecord(
            id=1,
            session_token="session-123",
            role="assistant",
            kind="assistant_welcome",
            content="Chao ban",
        )
    ]

    class FakeSessionService:
        def start_session(self):
            return ChatSessionSnapshot(session=session, messages=list(messages))

        def get_session_snapshot(self, session_token):
            return ChatSessionSnapshot(session=session, messages=list(messages))

    class FakeRepository:
        def create_run(self, session_token, profile_state):
            session["status"] = "running"
            session["latest_run_id"] = 7
            session["profile_state_json"] = profile_state.model_dump(mode="json")
            return 7

    class FakeConversationService:
        def __init__(self):
            self.repository = FakeRepository()
            self.turn_count = 0

        def handle_user_message(self, session_token, content):
            self.turn_count += 1
            messages.append(
                ChatMessageRecord(
                    id=len(messages) + 1,
                    session_token=session_token,
                    role="user",
                    kind="user_message",
                    content=content,
                )
            )
            if self.turn_count == 1:
                session["status"] = "collecting_profile"
                session["profile_state_json"] = {
                    "admission_year": 2026,
                    "preferred_majors": ["computer_science"],
                    "location_preference": "Ha Noi",
                    "missing_slots": ["total_score"],
                }
                messages.append(
                    ChatMessageRecord(
                        id=len(messages) + 1,
                        session_token=session_token,
                        role="assistant",
                        kind="assistant_follow_up",
                        content="Tong diem hoac muc diem uoc tinh cua ban la bao nhieu?",
                    )
                )
                return ConversationTurnResult(
                    session_status="collecting_profile",
                    assistant_message="Tong diem hoac muc diem uoc tinh cua ban la bao nhieu?",
                    should_start_run=False,
                    profile_state=ChatProfileState(
                        admission_year=2026,
                        preferred_majors=["computer_science"],
                        location_preference="Ha Noi",
                        missing_slots=["total_score"],
                    ),
                )

            ready_state = ChatProfileState(
                admission_year=2026,
                total_score=27.0,
                preferred_majors=["computer_science"],
                location_preference="Ha Noi",
                missing_slots=[],
            )
            session["status"] = "ready"
            session["profile_state_json"] = ready_state.model_dump(mode="json")
            messages.append(
                ChatMessageRecord(
                    id=len(messages) + 1,
                    session_token=session_token,
                    role="assistant",
                    kind="assistant_ready",
                    content="Cam on ban. Minh da co du thong tin va se bat dau phan tich.",
                )
            )
            return ConversationTurnResult(
                session_status="ready",
                assistant_message="Cam on ban. Minh da co du thong tin va se bat dau phan tich.",
                should_start_run=True,
                profile_state=ready_state,
            )

    class FakeDispatcher:
        def submit(self, session_token, run_id, latest_user_message, profile_state):
            session["status"] = "completed"
            messages.append(
                ChatMessageRecord(
                    id=len(messages) + 1,
                    session_token=session_token,
                    role="assistant",
                    kind="assistant_result",
                    content="De xuat: CNTT Bach Khoa Ha Noi la mot lua chon phu hop.",
                )
            )

    fake_session_service = FakeSessionService()
    fake_conversation_service = FakeConversationService()

    monkeypatch.setattr("web.routes.chat_api.get_session_service", lambda: fake_session_service)
    monkeypatch.setattr("web.routes.chat_api.get_conversation_service", lambda: fake_conversation_service)
    monkeypatch.setattr("web.routes.chat_api.get_run_dispatcher", lambda: FakeDispatcher())

    created = client.post("/api/sessions")
    assert created.status_code == 201

    first = client.post(
        "/api/sessions/session-123/messages",
        json={"content": "Em muon hoc CNTT o Ha Noi nam 2026"},
    )
    assert first.json()["should_start_run"] is False

    second = client.post(
        "/api/sessions/session-123/messages",
        json={"content": "Em du kien duoc 27 diem"},
    )
    assert second.json()["should_start_run"] is True

    snapshot = client.get("/api/sessions/session-123")
    body = snapshot.json()
    assert body["session"]["status"] == "completed"
    assert body["messages"][-1]["kind"] == "assistant_result"
    assert "Bach Khoa Ha Noi" in body["messages"][-1]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/e2e/test_chat_session_run_flow.py::test_student_can_complete_follow_up_and_receive_final_result -v`
Expected: FAIL because the file is currently empty and the demo critical path is not yet protected by a deterministic HTTP-level smoke test.

- [ ] **Step 3: Write minimal implementation**

```python
# web/routes/chat_api.py
@router.post("/{session_token}/messages")
def post_message(session_token: str, payload: ChatMessageCreate):
    service = get_conversation_service()
    result = service.handle_user_message(session_token, payload.content)
    if result.should_start_run:
        repo = service.repository
        run_id = repo.create_run(session_token, result.profile_state)
        get_run_dispatcher().submit(
            session_token=session_token,
            run_id=run_id,
            latest_user_message=payload.content,
            profile_state=result.profile_state,
        )
    return result.model_dump()
```

```python
# tests/e2e/test_chat_session_run_flow.py
from fastapi.testclient import TestClient

from services.chat.models import ChatMessageRecord, ChatProfileState, ChatSessionSnapshot, ConversationTurnResult
from web.app import build_app


def test_student_can_complete_follow_up_and_receive_final_result(monkeypatch):
    client = TestClient(build_app())

    session = {
        "id": 1,
        "session_token": "session-123",
        "status": "collecting_profile",
        "profile_state_json": {},
        "latest_run_id": None,
    }
    messages = [
        ChatMessageRecord(
            id=1,
            session_token="session-123",
            role="assistant",
            kind="assistant_welcome",
            content="Chao ban",
        )
    ]

    class FakeSessionService:
        def start_session(self):
            return ChatSessionSnapshot(session=session, messages=list(messages))

        def get_session_snapshot(self, session_token):
            return ChatSessionSnapshot(session=session, messages=list(messages))

    class FakeRepository:
        def create_run(self, session_token, profile_state):
            session["status"] = "running"
            session["latest_run_id"] = 7
            session["profile_state_json"] = profile_state.model_dump(mode="json")
            return 7

    class FakeConversationService:
        def __init__(self):
            self.repository = FakeRepository()
            self.turn_count = 0

        def handle_user_message(self, session_token, content):
            self.turn_count += 1
            messages.append(
                ChatMessageRecord(
                    id=len(messages) + 1,
                    session_token=session_token,
                    role="user",
                    kind="user_message",
                    content=content,
                )
            )
            if self.turn_count == 1:
                session["status"] = "collecting_profile"
                session["profile_state_json"] = {
                    "admission_year": 2026,
                    "preferred_majors": ["computer_science"],
                    "location_preference": "Ha Noi",
                    "missing_slots": ["total_score"],
                }
                messages.append(
                    ChatMessageRecord(
                        id=len(messages) + 1,
                        session_token=session_token,
                        role="assistant",
                        kind="assistant_follow_up",
                        content="Tong diem hoac muc diem uoc tinh cua ban la bao nhieu?",
                    )
                )
                return ConversationTurnResult(
                    session_status="collecting_profile",
                    assistant_message="Tong diem hoac muc diem uoc tinh cua ban la bao nhieu?",
                    should_start_run=False,
                    profile_state=ChatProfileState(
                        admission_year=2026,
                        preferred_majors=["computer_science"],
                        location_preference="Ha Noi",
                        missing_slots=["total_score"],
                    ),
                )

            ready_state = ChatProfileState(
                admission_year=2026,
                total_score=27.0,
                preferred_majors=["computer_science"],
                location_preference="Ha Noi",
                missing_slots=[],
            )
            session["status"] = "ready"
            session["profile_state_json"] = ready_state.model_dump(mode="json")
            messages.append(
                ChatMessageRecord(
                    id=len(messages) + 1,
                    session_token=session_token,
                    role="assistant",
                    kind="assistant_ready",
                    content="Cam on ban. Minh da co du thong tin va se bat dau phan tich.",
                )
            )
            return ConversationTurnResult(
                session_status="ready",
                assistant_message="Cam on ban. Minh da co du thong tin va se bat dau phan tich.",
                should_start_run=True,
                profile_state=ready_state,
            )

    class FakeDispatcher:
        def submit(self, session_token, run_id, latest_user_message, profile_state):
            session["status"] = "completed"
            messages.append(
                ChatMessageRecord(
                    id=len(messages) + 1,
                    session_token=session_token,
                    role="assistant",
                    kind="assistant_result",
                    content="De xuat: CNTT Bach Khoa Ha Noi la mot lua chon phu hop.",
                )
            )

    fake_session_service = FakeSessionService()
    fake_conversation_service = FakeConversationService()

    monkeypatch.setattr("web.routes.chat_api.get_session_service", lambda: fake_session_service)
    monkeypatch.setattr("web.routes.chat_api.get_conversation_service", lambda: fake_conversation_service)
    monkeypatch.setattr("web.routes.chat_api.get_run_dispatcher", lambda: FakeDispatcher())

    created = client.post("/api/sessions")
    assert created.status_code == 201

    first = client.post(
        "/api/sessions/session-123/messages",
        json={"content": "Em muon hoc CNTT o Ha Noi nam 2026"},
    )
    assert first.json()["should_start_run"] is False

    second = client.post(
        "/api/sessions/session-123/messages",
        json={"content": "Em du kien duoc 27 diem"},
    )
    assert second.json()["should_start_run"] is True

    snapshot = client.get("/api/sessions/session-123")
    body = snapshot.json()
    assert body["session"]["status"] == "completed"
    assert body["messages"][-1]["kind"] == "assistant_result"
    assert "Bach Khoa Ha Noi" in body["messages"][-1]["content"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/e2e/test_chat_session_run_flow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/routes/chat_api.py tests/e2e/test_chat_session_run_flow.py
git commit -m "test: cover complete student chat demo flow"
```

## Self-Review

Spec coverage in this plan:
- stale-session recovery and startup failure handling: covered by Task 1.
- one complete student flow from first message to final recommendation: covered by Task 2.
- final recommendation visibility through `assistant_result`: covered by Task 1 and Task 2.

Placeholder scan:
- No placeholder wording remains.

Type consistency:
- The plan consistently uses `assistant_result`, `profile_state_json`, `session.status`, and `ConversationTurnResult`.
