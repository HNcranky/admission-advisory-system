# Student Advisory Chat V1 - Phase 2: Anonymous Session API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add anonymous session lifecycle, transcript persistence, and HTTP endpoints that a future chat UI can call.

**Architecture:** Extend the repository with message storage, then add an `AnonymousSessionService` that owns token generation and initial assistant bootstrap. Expose the service through `/api/sessions` routes without adding follow-up intelligence or advisory execution yet.

**Tech Stack:** Python, FastAPI, Pydantic, PostgreSQL, `psycopg2-binary`, `pytest`, `fastapi.testclient`

---

## Planned File Structure

- `services/chat/models.py`
  - Add message and snapshot response models.
- `services/chat/repository.py`
  - Add message persistence and session fetch helpers.
- `services/chat/session_service.py`
  - Generate anonymous tokens and bootstrap new chat sessions.
- `web/routes/chat_api.py`
  - Public JSON endpoints for session creation and retrieval.

### Task 1: Add Anonymous Session Service And Transcript Persistence

**Files:**
- Modify: `services/chat/models.py`
- Modify: `services/chat/repository.py`
- Create: `services/chat/session_service.py`
- Test: `tests/services/chat/test_session_service.py`

- [ ] **Step 1: Write the failing test**

```python
from services.chat.models import ChatMessageRecord
from services.chat.session_service import AnonymousSessionService


class FakeRepository:
    def __init__(self):
        self.session = None
        self.messages = []

    def create_session(self, session_token):
        self.session = {
            "id": 1,
            "session_token": session_token,
            "status": "collecting_profile",
            "profile_state_json": {},
            "latest_run_id": None,
        }
        return self.session

    def append_message(self, session_token, role, content, kind="chat"):
        message = ChatMessageRecord(
            id=len(self.messages) + 1,
            session_token=session_token,
            role=role,
            kind=kind,
            content=content,
        )
        self.messages.append(message)
        return message


def test_start_session_creates_welcome_message():
    service = AnonymousSessionService(repository=FakeRepository())

    snapshot = service.start_session()

    assert snapshot.session["status"] == "collecting_profile"
    assert snapshot.messages[0].role == "assistant"
    assert "cho minh biet diem" in snapshot.messages[0].content.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/chat/test_session_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.chat.session_service'`

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
```

```python
# services/chat/repository.py
    def append_message(self, session_token: str, role: str, content: str, kind: str = "chat"):
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO chat_messages (session_id, role, kind, content)
            SELECT id, %s, %s, %s
            FROM chat_sessions
            WHERE session_token = %s
            RETURNING id
            """,
            (role, kind, content, session_token),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return ChatMessageRecord(
            id=row[0],
            session_token=session_token,
            role=role,
            kind=kind,
            content=content,
        )

    def list_messages(self, session_token: str):
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT m.id, s.session_token, m.role, m.kind, m.content
            FROM chat_messages m
            JOIN chat_sessions s ON s.id = m.session_id
            WHERE s.session_token = %s
            ORDER BY m.created_at ASC, m.id ASC
            """,
            (session_token,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            ChatMessageRecord(
                id=row[0],
                session_token=row[1],
                role=row[2],
                kind=row[3],
                content=row[4],
            )
            for row in rows
        ]
```

```python
# services/chat/session_service.py
import secrets

from services.chat.models import ChatSessionSnapshot
from services.chat.repository import ChatSessionRepository


WELCOME_MESSAGE = (
    "Chao ban, minh co the tu van tuyen sinh. "
    "Hay cho minh biet diem, nganh ban quan tam, va khu vuc ban muon hoc."
)


class AnonymousSessionService:
    def __init__(self, repository=None):
        self.repository = repository or ChatSessionRepository()

    def start_session(self) -> ChatSessionSnapshot:
        session_token = secrets.token_urlsafe(18)
        session = self.repository.create_session(session_token)
        welcome = self.repository.append_message(
            session_token,
            role="assistant",
            content=WELCOME_MESSAGE,
            kind="assistant_welcome",
        )
        return ChatSessionSnapshot(session=session, messages=[welcome])

    def get_session_snapshot(self, session_token: str) -> ChatSessionSnapshot:
        session = self.repository.get_session_by_token(session_token)
        messages = self.repository.list_messages(session_token)
        return ChatSessionSnapshot(session=session, messages=messages)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/chat/test_session_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/chat/models.py services/chat/repository.py services/chat/session_service.py tests/services/chat/test_session_service.py
git commit -m "feat: add anonymous session bootstrap service"
```

### Task 2: Add Session Bootstrap And Read Endpoints

**Files:**
- Modify: `web/app.py`
- Create: `web/routes/chat_api.py`
- Test: `tests/web/test_chat_session_api.py`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from services.chat.models import ChatSessionSnapshot
from web.app import build_app


def test_create_session_endpoint_returns_token_and_welcome_message():
    client = TestClient(build_app())

    response = client.post("/api/sessions")

    assert response.status_code == 201
    body = response.json()
    assert body["session"]["status"] == "collecting_profile"
    assert body["messages"][0]["role"] == "assistant"
    assert body["messages"][0]["kind"] == "assistant_welcome"


def test_get_session_endpoint_returns_existing_snapshot(monkeypatch):
    client = TestClient(build_app())

    class FakeService:
        def get_session_snapshot(self, session_token):
            return ChatSessionSnapshot(
                session={
                    "id": 1,
                    "session_token": session_token,
                    "status": "collecting_profile",
                    "profile_state_json": {},
                    "latest_run_id": None,
                },
                messages=[],
            )

    monkeypatch.setattr("web.routes.chat_api.get_session_service", lambda: FakeService())

    response = client.get("/api/sessions/session-123")

    assert response.status_code == 200
    assert response.json()["session"]["session_token"] == "session-123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_chat_session_api.py -v`
Expected: FAIL with `404 Not Found` for `/api/sessions`

- [ ] **Step 3: Write minimal implementation**

```python
# web/routes/chat_api.py
from fastapi import APIRouter, HTTPException, status

from services.chat.session_service import AnonymousSessionService


router = APIRouter(prefix="/api/sessions", tags=["chat"])


def get_session_service():
    return AnonymousSessionService()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_session():
    service = get_session_service()
    return service.start_session().model_dump()


@router.get("/{session_token}")
def get_session(session_token: str):
    service = get_session_service()
    snapshot = service.get_session_snapshot(session_token)
    if snapshot.session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    return snapshot.model_dump()
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
git add web/app.py web/routes/chat_api.py tests/web/test_chat_session_api.py
git commit -m "feat: add anonymous session api"
```

## Self-Review

Spec coverage in this plan:
- Anonymous session bootstrap: covered by Task 1 and Task 2.
- Stored transcript foundation: covered by Task 1.
- Public API surface for the future UI: covered by Task 2.

Intentional exclusions from this plan:
- No profile follow-up logic yet.
- No advisory run orchestration yet.
- No HTML UI yet.

Plan complete and saved to `docs/superpowers/plans/2026-05-01-student-advisory-chat-v1/02-anonymous-session-api.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
