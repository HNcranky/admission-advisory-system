# Student Chat E2E Demo - Plan 1: Session API And Transcript Snapshots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the backend session contract so the browser can create a chat session, fetch a session snapshot, and read transcript history reliably.

**Architecture:** Reuse the existing `AnonymousSessionService` and `ChatSessionRepository` instead of inventing a second demo path. Fix transcript retrieval first, then expose `POST /api/sessions` and `GET /api/sessions/{session_token}` beside the existing message endpoint, using the session snapshot model as the shared response shape.

**Tech Stack:** Python, FastAPI, Pydantic, PostgreSQL, `pytest`, `fastapi.testclient`

---

## Planned File Structure

- `services/chat/repository.py`
  - Fix transcript query correctness and keep `list_message()` as the service-facing snapshot primitive for this branch.
- `services/chat/session_service.py`
  - Keep session bootstrap and snapshot retrieval behavior thin and repository-backed.
- `web/routes/chat_api.py`
  - Add session create/read endpoints and missing session-service dependency helper.
- `tests/services/chat/test_repository.py`
  - Add a regression test for transcript listing.
- `tests/services/chat/test_session_service.py`
  - Add snapshot retrieval coverage.
- `tests/web/test_chat_session_api.py`
  - Add create/read route coverage and 404 behavior for missing sessions.

### Task 1: Fix Transcript Snapshot Retrieval In The Repository

**Files:**
- Modify: `services/chat/repository.py`
- Test: `tests/services/chat/test_repository.py`

- [ ] **Step 1: Write the failing test**

```python
from services.chat.repository import ChatSessionRepository


class FakeCursor:
    def __init__(self):
        self.statements = []
        self._row = (
            1,
            "session-123",
            "collecting_profile",
            {},
            None,
        )
        self._rows = [
            (1, "session-123", "assistant", "assistant_welcome", "Chao ban"),
            (2, "session-123", "user", "user_message", "Em muon hoc CNTT"),
        ]

    def execute(self, sql, params):
        self.statements.append((sql, params))

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows

    def close(self):
        return None


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        return None


def test_list_message_returns_transcript_in_order():
    connection = FakeConnection()
    repo = ChatSessionRepository(connection_factory=lambda: connection)

    messages = repo.list_message("session-123")

    assert [message.kind for message in messages] == [
        "assistant_welcome",
        "user_message",
    ]
    sql = connection.cursor_obj.statements[0][0]
    assert "JOIN chat_sessions s ON s.id = m.session_id" in sql
    assert "WHERE s.session_token = %s" in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/chat/test_repository.py::test_list_message_returns_transcript_in_order -v`
Expected: FAIL because the current SQL in `list_message()` uses `chat_Sessions` and `mession_id`, so the assertion for `JOIN chat_sessions s ON s.id = m.session_id` does not match.

- [ ] **Step 3: Write minimal implementation**

```python
# services/chat/repository.py
from services.chat.db import get_db_connection
from services.chat.models import ChatSessionRecord, ChatMessageRecord, ChatProfileState


class ChatSessionRepository:
    def __init__(self, connection_factory=get_db_connection):
        self.connection_factory = connection_factory

    def create_session(self, session_token: str) -> ChatSessionRecord:
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO chat_sessions (session_token)
            VALUES (%s)
            RETURNING id, session_token, status, profile_state_json, latest_run_id
            """,
            (session_token,),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return ChatSessionRecord(
            id=row[0],
            session_token=row[1],
            status=row[2],
            profile_state_json=row[3] or {},
            latest_run_id=row[4],
        )

    def get_session_by_token(self, session_token: str):
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, session_token, status, profile_state_json, latest_run_id
            FROM chat_sessions
            WHERE session_token = %s
            """,
            (session_token,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        return ChatSessionRecord(
            id=row[0],
            session_token=row[1],
            status=row[2],
            profile_state_json=row[3] or {},
            latest_run_id=row[4],
        )

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

    def list_message(self, session_token: str):
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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/chat/test_repository.py::test_list_message_returns_transcript_in_order -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/chat/repository.py tests/services/chat/test_repository.py
git commit -m "fix: restore chat transcript snapshot query"
```

### Task 2: Add Session Snapshot Coverage In The Session Service

**Files:**
- Modify: `tests/services/chat/test_session_service.py`
- Modify: `services/chat/session_service.py`

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

    def get_session_by_token(self, session_token):
        return self.session

    def list_message(self, session_token):
        return self.messages


def test_get_session_snapshot_returns_existing_messages():
    repository = FakeRepository()
    service = AnonymousSessionService(repository=repository)
    snapshot = service.start_session()

    fetched = service.get_session_snapshot(snapshot.session["session_token"])

    assert fetched.session["session_token"] == snapshot.session["session_token"]
    assert fetched.messages[0].kind == "assistant_welcome"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/chat/test_session_service.py::test_get_session_snapshot_returns_existing_messages -v`
Expected: FAIL because the current test file does not yet define the snapshot retrieval test coverage.

- [ ] **Step 3: Write minimal implementation**

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
        messages = self.repository.list_message(session_token) if session else []
        return ChatSessionSnapshot(session=session, messages=messages)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/chat/test_session_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/chat/session_service.py tests/services/chat/test_session_service.py
git commit -m "test: cover chat session snapshot retrieval"
```

### Task 3: Expose Session Create And Session Read Endpoints

**Files:**
- Modify: `web/routes/chat_api.py`
- Modify: `tests/web/test_chat_session_api.py`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from services.chat.models import ChatMessageRecord, ChatSessionSnapshot
from web.app import build_app


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
                        content="Chao ban",
                    )
                ],
            )

    monkeypatch.setattr("web.routes.chat_api.get_session_service", lambda: FakeSessionService())

    response = client.post("/api/sessions")

    assert response.status_code == 201
    body = response.json()
    assert body["session"]["session_token"] == "session-123"
    assert body["messages"][0]["kind"] == "assistant_welcome"


def test_get_session_endpoint_returns_404_when_missing(monkeypatch):
    client = TestClient(build_app())

    class FakeSessionService:
        def get_session_snapshot(self, session_token):
            return ChatSessionSnapshot(session=None, messages=[])

    monkeypatch.setattr("web.routes.chat_api.get_session_service", lambda: FakeSessionService())

    response = client.get("/api/sessions/missing-token")

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_chat_session_api.py::test_create_session_endpoint_returns_snapshot tests/web/test_chat_session_api.py::test_get_session_endpoint_returns_404_when_missing -v`
Expected: FAIL with `AttributeError` for `get_session_service` or `404 Not Found` for `POST /api/sessions` because those routes do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# web/routes/chat_api.py
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from services.chat.conversation_service import ConversationService
from services.chat.run_dispatcher import RunDispatcher
from services.chat.session_service import AnonymousSessionService


router = APIRouter(prefix="/api/sessions", tags=["chat"])


class ChatMessageCreate(BaseModel):
    content: str


def get_session_service():
    return AnonymousSessionService()


def get_conversation_service():
    return ConversationService()


def get_run_dispatcher():
    return RunDispatcher()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_session():
    return get_session_service().start_session()


@router.get("/{session_token}")
def get_session(session_token: str):
    snapshot = get_session_service().get_session_snapshot(session_token)
    if not snapshot.session:
        raise HTTPException(status_code=404, detail="Session not found")
    return snapshot


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

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/web/test_chat_session_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/routes/chat_api.py tests/web/test_chat_session_api.py
git commit -m "feat: add chat session create and snapshot endpoints"
```

## Self-Review

Spec coverage in this plan:
- `POST /api/sessions`: covered by Task 3.
- `GET /api/sessions/{session_token}`: covered by Task 3.
- reliable transcript snapshot source of truth: covered by Task 1 and Task 2.

Placeholder scan:
- No `TODO`, `TBD`, or “implement later” markers remain.

Type consistency:
- The plan consistently uses `ChatSessionSnapshot`, `ChatMessageRecord`, `list_message()`, and `get_session_service()`.
