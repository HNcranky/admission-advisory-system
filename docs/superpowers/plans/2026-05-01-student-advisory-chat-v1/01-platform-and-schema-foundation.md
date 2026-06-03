# Student Advisory Chat V1 - Phase 1: Platform And Schema Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the web application skeleton and persistent storage foundation for anonymous chat sessions without changing advisory behavior yet.

**Architecture:** Add a small `web/` FastAPI application beside the existing graph entrypoint, then add a chat-specific SQL migration and repository layer under `services/chat/`. This slice deliberately stops at health checks and typed storage primitives so later phases can build chat behavior on stable interfaces.

**Tech Stack:** Python, FastAPI, Uvicorn, Pydantic, PostgreSQL, `psycopg2-binary`, `pytest`, `fastapi.testclient`

---

## Planned File Structure

- `web/app.py`
  - FastAPI app factory and router registration.
- `web/routes/system.py`
  - Health endpoint used by tests and local bootstrapping.
- `services/chat/models.py`
  - Typed records for sessions and later chat state.
- `services/chat/db.py`
  - Shared `psycopg2` connection helper for chat repositories.
- `services/chat/repository.py`
  - Low-level chat session persistence methods.
- `db/migrations/009_chat_sessions.sql`
  - New tables for `chat_sessions`, `chat_messages`, and `chat_advisory_runs`.

### Task 1: Add FastAPI App Skeleton And Health Route

**Files:**
- Modify: `requirements.txt`
- Create: `web/__init__.py`
- Create: `web/app.py`
- Create: `web/routes/__init__.py`
- Create: `web/routes/system.py`
- Test: `tests/web/test_system_routes.py`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from web.app import build_app


def test_health_route_returns_ok():
    client = TestClient(build_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_system_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web'`

- [ ] **Step 3: Write minimal implementation**

```text
# requirements.txt
fastapi
uvicorn
jinja2
httpx
```

```python
# web/routes/system.py
from fastapi import APIRouter


router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}
```

```python
# web/app.py
from fastapi import FastAPI

from web.routes.system import router as system_router


def build_app() -> FastAPI:
    app = FastAPI(title="Student Advisory Chat")
    app.include_router(system_router)
    return app
```

```python
# web/__init__.py
from web.app import build_app

__all__ = ["build_app"]
```

```python
# web/routes/__init__.py
from web.routes.system import router as system_router

__all__ = ["system_router"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/web/test_system_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt web/__init__.py web/app.py web/routes/__init__.py web/routes/system.py tests/web/test_system_routes.py
git commit -m "feat: add web app skeleton"
```

### Task 2: Add Chat Storage Schema And Typed Repository Primitives

**Files:**
- Create: `db/migrations/009_chat_sessions.sql`
- Modify: `db/setup_db.py`
- Create: `services/chat/__init__.py`
- Create: `services/chat/models.py`
- Create: `services/chat/db.py`
- Create: `services/chat/repository.py`
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

    def execute(self, sql, params):
        self.statements.append((sql, params))

    def fetchone(self):
        return self._row

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


def test_create_session_persists_token_and_returns_record():
    connection = FakeConnection()
    repo = ChatSessionRepository(connection_factory=lambda: connection)

    session = repo.create_session("session-123")

    assert session.session_token == "session-123"
    assert session.status == "collecting_profile"
    assert "INSERT INTO chat_sessions" in connection.cursor_obj.statements[0][0]
    assert connection.committed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/services/chat/test_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.chat'`

- [ ] **Step 3: Write minimal implementation**

```sql
-- db/migrations/009_chat_sessions.sql
CREATE TABLE IF NOT EXISTS chat_sessions (
    id SERIAL PRIMARY KEY,
    session_token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'collecting_profile',
    profile_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    latest_run_id INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'chat',
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_advisory_runs (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued',
    profile_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB,
    final_answer TEXT,
    error_text TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at
ON chat_sessions (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
ON chat_messages (session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_chat_advisory_runs_session_id
ON chat_advisory_runs (session_id, created_at DESC);
```

```python
# services/chat/models.py
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ChatSessionRecord(BaseModel):
    id: int
    session_token: str
    status: str = "collecting_profile"
    profile_state_json: Dict[str, Any] = Field(default_factory=dict)
    latest_run_id: Optional[int] = None
```

```python
# services/chat/db.py
import psycopg2

from ingestion.config.settings import DB_CONFIG


def get_db_connection():
    return psycopg2.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        database=DB_CONFIG["database"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )
```

```python
# services/chat/repository.py
from services.chat.db import get_db_connection
from services.chat.models import ChatSessionRecord


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
```

```python
# services/chat/__init__.py
from services.chat.models import ChatSessionRecord
from services.chat.repository import ChatSessionRepository

__all__ = ["ChatSessionRecord", "ChatSessionRepository"]
```

```python
# db/setup_db.py
expected = [
    "source_registry",
    "discovered_resources",
    "raw_documents",
    "extracted_facts",
    "canonical_admission_records",
    "advisory_runs",
    "chat_sessions",
    "chat_messages",
    "chat_advisory_runs",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/services/chat/test_repository.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add db/migrations/009_chat_sessions.sql db/setup_db.py services/chat/__init__.py services/chat/models.py services/chat/db.py services/chat/repository.py tests/services/chat/test_repository.py
git commit -m "feat: add chat storage foundation"
```

## Self-Review

Spec coverage in this plan:
- Public app foundation: covered by Task 1.
- Session and run persistence schema: covered by Task 2.
- Reusable typed storage layer: covered by Task 2.

Intentional exclusions from this plan:
- No anonymous session HTTP flow yet.
- No follow-up logic yet.
- No advisory graph execution yet.

Plan complete and saved to `docs/superpowers/plans/2026-05-01-student-advisory-chat-v1/01-platform-and-schema-foundation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
