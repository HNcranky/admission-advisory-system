# Student Advisory Chat V1 - Phase 3: Profile State And Follow-Up Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn raw user chat messages into progressively richer structured profile state and return exactly one focused follow-up question until the session is ready for advisory execution.

**Architecture:** Reuse `build_profile_with_gateway()` for per-turn extraction, then merge that extraction into a chat-owned `ChatProfileState` model that tracks admission year plus the ordered list of critical missing slots. Keep the decision boundary in `ConversationService`: this phase may persist a `ready` session and return `should_start_run=True`, but it must not create or dispatch advisory runs yet.

**Tech Stack:** Python, FastAPI, Pydantic, existing Gemini gateway, `pytest`, `monkeypatch`, `fastapi.testclient`

---

## Planned File Structure

- `services/chat/models.py`
  - Keep chat-specific response and profile-state models in one place.
- `services/chat/profile_state_service.py`
  - Own merge rules, admission-year extraction, missing-slot ordering, and follow-up question selection.
- `services/chat/repository.py`
  - Read and persist `profile_state_json` and session status for each turn.
- `services/chat/conversation_service.py`
  - Append user/assistant transcript messages, merge state, and decide between follow-up versus ready.
- `web/routes/chat_api.py`
  - Expose the message POST endpoint for an existing session.
- `web/app.py`
  - Mount the chat router so the new message endpoint is reachable.
- `tests/services/chat/test_profile_state_service.py`
  - Lock merge semantics, slot ordering, and prompt selection.
- `tests/services/chat/test_conversation_service.py`
  - Lock the state-machine boundary: follow-up path versus ready path.
- `tests/web/test_chat_session_api.py`
  - Lock the HTTP contract for posting a chat message.

### Task 1: Add Deterministic Profile-State Merge Logic

**Files:**
- Modify: `services/chat/models.py`
- Create: `services/chat/profile_state_service.py`
- Test: `tests/services/chat/test_profile_state_service.py`

- [ ] **Step 1: Write the failing test**

```python
from agents.models import StudentProfile
from services.chat.models import ChatProfileState
from services.chat.profile_state_service import (
    merge_profile_state,
    next_follow_up_question,
)


def test_merge_profile_state_keeps_previous_values_and_orders_missing_slots():
    current = ChatProfileState(
        admission_year=2026,
        preferred_majors=["computer_science"],
    )
    extracted = StudentProfile(
        total_score=27.0,
        location_preference="Ha Noi",
    )

    merged = merge_profile_state(
        current,
        extracted,
        "Em duoc khoang 27 diem va muon hoc tai Ha Noi",
    )

    assert merged.admission_year == 2026
    assert merged.total_score == 27.0
    assert merged.preferred_majors == ["computer_science"]
    assert merged.location_preference == "Ha Noi"
    assert merged.missing_slots == []
    assert next_follow_up_question(merged) is None


def test_merge_profile_state_returns_first_missing_slot_prompt():
    merged = merge_profile_state(
        ChatProfileState(),
        StudentProfile(preferred_majors=["kinh_te"]),
        "Em muon hoc khoi kinh te",
    )

    assert merged.missing_slots == [
        "admission_year",
        "total_score",
        "location_preference",
    ]
    assert next_follow_up_question(merged) == "Ban dang xet tuyen cho nam nao?"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/chat/test_profile_state_service.py -v`
Expected: FAIL because `merge_profile_state()` and `next_follow_up_question()` do not yet preserve prior values and ordered missing-slot behavior exactly as asserted.

- [ ] **Step 3: Write minimal implementation**

```python
# services/chat/models.py
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatSessionRecord(BaseModel):
    id: int
    session_token: str
    status: str = "collecting_profile"
    profile_state_json: Dict[str, Any] = Field(default_factory=dict)
    latest_run_id: Optional[int] = None


class ChatMessageRecord(BaseModel):
    id: int
    session_token: str
    role: str
    kind: str = "chat"
    content: str


class ChatSessionSnapshot(BaseModel):
    session: Any
    messages: List[ChatMessageRecord] = Field(default_factory=list)


class ChatProfileState(BaseModel):
    admission_year: Optional[int] = None
    total_score: Optional[float] = None
    subject_combination: Optional[str] = None
    preferred_majors: List[str] = Field(default_factory=list)
    preferred_schools: List[str] = Field(default_factory=list)
    location_preference: Optional[str] = None
    tuition_budget: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    missing_slots: List[str] = Field(default_factory=list)
```

```python
# services/chat/profile_state_service.py
import re

from agents.models import StudentProfile
from services.chat.models import ChatProfileState


CRITICAL_SLOT_ORDER = [
    "admission_year",
    "total_score",
    "preferred_majors",
    "location_preference",
]


FOLLOW_UP_PROMPTS = {
    "admission_year": "Ban dang xet tuyen cho nam nao?",
    "total_score": "Tong diem hoac muc diem uoc tinh cua ban la bao nhieu?",
    "preferred_majors": "Ban quan tam nhat den nganh nao?",
    "location_preference": "Ban muon hoc o khu vuc hay thanh pho nao?",
}


def _extract_admission_year(raw_message: str) -> int | None:
    match = re.search(r"\b20\d{2}\b", raw_message)
    return int(match.group(0)) if match else None


def merge_profile_state(
    current: ChatProfileState,
    extracted: StudentProfile,
    raw_message: str,
) -> ChatProfileState:
    merged = ChatProfileState(
        admission_year=_extract_admission_year(raw_message) or current.admission_year,
        total_score=extracted.total_score or current.total_score,
        subject_combination=extracted.subject_combination or current.subject_combination,
        preferred_majors=extracted.preferred_majors or current.preferred_majors,
        preferred_schools=extracted.preferred_schools or current.preferred_schools,
        location_preference=extracted.location_preference or current.location_preference,
        tuition_budget=extracted.tuition_budget or current.tuition_budget,
        constraints=extracted.constraints or current.constraints,
    )
    merged.missing_slots = [
        slot
        for slot in CRITICAL_SLOT_ORDER
        if not getattr(merged, slot)
    ]
    return merged


def next_follow_up_question(state: ChatProfileState) -> str | None:
    if not state.missing_slots:
        return None
    return FOLLOW_UP_PROMPTS[state.missing_slots[0]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/chat/test_profile_state_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/chat/models.py services/chat/profile_state_service.py tests/services/chat/test_profile_state_service.py
git commit -m "feat: add chat profile-state merge logic"
```

### Task 2: Add Conversation State-Machine Orchestration

**Files:**
- Modify: `services/chat/models.py`
- Modify: `services/chat/repository.py`
- Create or Modify: `services/chat/conversation_service.py`
- Test: `tests/services/chat/test_conversation_service.py`

- [ ] **Step 1: Write the failing test**

```python
from agents.models import StudentProfile
from services.chat.conversation_service import ConversationService
from services.chat.models import ChatProfileState


class FakeRepository:
    def __init__(self):
        self.profile_state = ChatProfileState()
        self.messages = []
        self.status = "collecting_profile"

    def append_message(self, session_token, role, content, kind="chat"):
        self.messages.append((role, kind, content))

    def get_profile_state(self, session_token):
        return self.profile_state

    def update_profile_state(self, session_token, profile_state, status):
        self.profile_state = profile_state
        self.status = status
        return profile_state


def test_handle_user_message_returns_follow_up_when_score_missing():
    repo = FakeRepository()
    service = ConversationService(
        repository=repo,
        extract_profile=lambda text: StudentProfile(
            preferred_majors=["computer_science"],
            location_preference="Ha Noi",
        ),
    )

    result = service.handle_user_message(
        "session-123",
        "Em muon hoc CNTT tai Ha Noi nam 2026",
    )

    assert result.session_status == "collecting_profile"
    assert result.should_start_run is False
    assert result.profile_state.missing_slots == ["total_score"]
    assert repo.messages[-1][1] == "assistant_follow_up"
    assert "bao nhieu" in result.assistant_message.lower()


def test_handle_user_message_marks_session_ready_without_dispatching_run():
    repo = FakeRepository()
    service = ConversationService(
        repository=repo,
        extract_profile=lambda text: StudentProfile(
            total_score=27.0,
            preferred_majors=["computer_science"],
            location_preference="Ha Noi",
        ),
    )

    result = service.handle_user_message(
        "session-123",
        "Em muon hoc CNTT tai Ha Noi nam 2026 va duoc 27 diem",
    )

    assert result.session_status == "ready"
    assert result.should_start_run is True
    assert result.profile_state.missing_slots == []
    assert repo.status == "ready"
    assert repo.messages[-1][1] == "assistant_ready"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/chat/test_conversation_service.py -v`
Expected: FAIL because the ready-path assertions and persisted status/message kind are not yet covered or do not match the implementation exactly.

- [ ] **Step 3: Write minimal implementation**

```python
# services/chat/models.py
class ConversationTurnResult(BaseModel):
    session_status: str
    assistant_message: str
    should_start_run: bool = False
    profile_state: ChatProfileState
```

```python
# services/chat/repository.py
from services.chat.db import get_db_connection
from services.chat.models import ChatMessageRecord, ChatProfileState, ChatSessionRecord


class ChatSessionRepository:
    def __init__(self, connection_factory=get_db_connection):
        self.connection_factory = connection_factory

    def get_profile_state(self, session_token: str):
        session = self.get_session_by_token(session_token)
        return ChatProfileState(**session.profile_state_json) if session else ChatProfileState()

    def update_profile_state(self, session_token: str, profile_state, status: str):
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE chat_sessions
            SET profile_state_json = %s, status = %s, updated_at = NOW()
            WHERE session_token = %s
            """,
            (profile_state.model_dump(mode="json"), status, session_token),
        )
        conn.commit()
        cur.close()
        conn.close()
        return profile_state
```

```python
# services/chat/conversation_service.py
from services import build_default_gateway
from services.chat.models import ConversationTurnResult
from services.chat.profile_state_service import merge_profile_state, next_follow_up_question
from services.chat.repository import ChatSessionRepository
from services.profile_inference_service import build_profile_with_gateway


READY_MESSAGE = "Cam on ban. Minh da co du thong tin va se bat dau phan tich."


class ConversationService:
    def __init__(self, repository=None, extract_profile=None):
        self.repository = repository or ChatSessionRepository()
        self.extract_profile = extract_profile or self._extract_profile

    def _extract_profile(self, text: str):
        gateway = build_default_gateway()
        return build_profile_with_gateway(text, gateway)

    def handle_user_message(self, session_token: str, content: str) -> ConversationTurnResult:
        self.repository.append_message(session_token, "user", content, "user_message")
        current = self.repository.get_profile_state(session_token)
        extracted = self.extract_profile(content)
        merged = merge_profile_state(current, extracted, content)

        follow_up = next_follow_up_question(merged)
        if follow_up:
            self.repository.update_profile_state(session_token, merged, "collecting_profile")
            self.repository.append_message(
                session_token,
                "assistant",
                follow_up,
                "assistant_follow_up",
            )
            return ConversationTurnResult(
                session_status="collecting_profile",
                assistant_message=follow_up,
                should_start_run=False,
                profile_state=merged,
            )

        self.repository.update_profile_state(session_token, merged, "ready")
        self.repository.append_message(
            session_token,
            "assistant",
            READY_MESSAGE,
            "assistant_ready",
        )
        return ConversationTurnResult(
            session_status="ready",
            assistant_message=READY_MESSAGE,
            should_start_run=True,
            profile_state=merged,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/chat/test_conversation_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/chat/models.py services/chat/repository.py services/chat/conversation_service.py tests/services/chat/test_conversation_service.py
git commit -m "feat: add chat follow-up decision service"
```

### Task 3: Expose The Message Endpoint Through FastAPI

**Files:**
- Modify: `web/routes/chat_api.py`
- Modify: `web/app.py`
- Test: `tests/web/test_chat_session_api.py`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from services.chat.models import ChatProfileState, ConversationTurnResult
from web.app import build_app


def test_post_message_returns_follow_up_payload(monkeypatch):
    client = TestClient(build_app())

    class FakeService:
        def handle_user_message(self, session_token, content):
            assert session_token == "session-123"
            assert content == "Em muon hoc CNTT"
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

    class FakeService:
        def handle_user_message(self, session_token, content):
            return ConversationTurnResult(
                session_status="ready",
                assistant_message="Cam on ban. Minh da co du thong tin va se bat dau phan tich.",
                should_start_run=True,
                profile_state=ChatProfileState(
                    admission_year=2026,
                    total_score=27.0,
                    preferred_majors=["computer_science"],
                    location_preference="Ha Noi",
                    missing_slots=[],
                ),
            )

    monkeypatch.setattr("web.routes.chat_api.get_conversation_service", lambda: FakeService())

    response = client.post(
        "/api/sessions/session-123/messages",
        json={"content": "Em muon hoc CNTT tai Ha Noi nam 2026 va duoc 27 diem"},
    )

    assert response.status_code == 200
    assert response.json()["should_start_run"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_chat_session_api.py -v`
Expected: FAIL with `404 Not Found` for `/api/sessions/session-123/messages` until the chat router is mounted and the route exists.

- [ ] **Step 3: Write minimal implementation**

```python
# web/routes/chat_api.py
from fastapi import APIRouter
from pydantic import BaseModel

from services.chat.conversation_service import ConversationService


router = APIRouter(prefix="/api/sessions", tags=["chat"])


class ChatMessageCreate(BaseModel):
    content: str


def get_conversation_service():
    return ConversationService()


@router.post("/{session_token}/messages")
def post_message(session_token: str, payload: ChatMessageCreate):
    service = get_conversation_service()
    result = service.handle_user_message(session_token, payload.content)
    return result.model_dump()
```

```python
# web/app.py
from fastapi import FastAPI

from web.routes.chat_api import router as chat_router
from web.routes.system import router as system_router


def build_app() -> FastAPI:
    app = FastAPI(title="Student Advisory Chat")
    app.include_router(system_router)
    app.include_router(chat_router)
    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/web/test_chat_session_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/routes/chat_api.py web/app.py tests/web/test_chat_session_api.py
git commit -m "feat: add chat message api endpoint"
```

## Self-Review

Spec coverage in this plan:
- Progressive profile capture from natural-language input: covered by Task 1.
- One-targeted-follow-up-question-at-a-time behavior: covered by Task 1 and Task 2.
- Session-level decision boundary between `collecting_profile` and `ready`: covered by Task 2.
- Public message-flow API coverage for an existing session: covered by Task 3.
- Explicit non-dispatch behavior in this phase: covered by Task 2 and Task 3 through `should_start_run` only.

Intentional exclusions from this plan:
- No advisory run record creation yet.
- No background execution or graph invocation yet.
- No public HTML chat UI yet.

Plan complete and saved to `docs/superpowers/plans/2026-05-01-student-advisory-chat-v1/03-profile-state-and-follow-up-orchestration.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
