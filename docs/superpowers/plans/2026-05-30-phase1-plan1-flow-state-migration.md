# Phase 1 — Plan 1: FlowState Model + DB Migration + Repository

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `FlowState` Pydantic model, a DB migration for the `flow_state_json` column, and two repository methods (`get_flow_state`, `update_flow_state`) — the storage foundation for Phase 1 routing.

**Architecture:** `FlowState` lives in `services/chat/models.py` next to `ChatProfileState`. It has exactly two fields — `active_flow` and `pending_question` — because "is the user mid-advisory-flow?" is derived from those two (`active_flow == "ADVISORY_FLOW" and pending_question is not None`), not stored as a separate flag. A new JSONB column `flow_state_json` is added to `chat_sessions` via an idempotent migration. Two methods are added to `ChatSessionRepository` following the exact psycopg2 tuple-cursor pattern already used by `get_profile_state` / `update_profile_state` (raw `conn.cursor()`, `row[0]`, `self._jsonb(...)`, commit/close).

**Tech Stack:** Python 3.11, Pydantic v2, psycopg2, PostgreSQL, pytest, unittest.mock

**Spec:** `docs/superpowers/specs/2026-05-30-phase1-intent-router-flow-state-design.md` (§2 FlowState, §3 Migration, §4 Repository)

---

### Task 1: FlowState Pydantic Model

**Files:**
- Modify: `services/chat/models.py` (add class after `ChatProfileState`, line 33)
- Test: `tests/services/chat/test_flow_state_model.py`

- [ ] **Step 1: Create test file and write failing tests**

Create `tests/services/chat/test_flow_state_model.py`:

```python
from services.chat.models import FlowState


def test_flow_state_defaults():
    state = FlowState()
    assert state.active_flow is None
    assert state.pending_question is None


def test_flow_state_model_validate_from_empty_dict():
    state = FlowState.model_validate({})
    assert state == FlowState()


def test_flow_state_model_validate_from_full_dict():
    state = FlowState.model_validate({
        "active_flow": "ADVISORY_FLOW",
        "pending_question": "Bạn học khối gì?",
    })
    assert state.active_flow == "ADVISORY_FLOW"
    assert state.pending_question == "Bạn học khối gì?"


def test_flow_state_model_copy_update_does_not_mutate_original():
    original = FlowState(active_flow="ADVISORY_FLOW")
    updated = original.model_copy(update={"pending_question": "Q?"})
    assert updated.active_flow == "ADVISORY_FLOW"
    assert updated.pending_question == "Q?"
    assert original.pending_question is None


def test_flow_state_ignores_legacy_return_to_flow_key():
    """Old rows may still contain return_to_flow; it must be ignored, not raise."""
    state = FlowState.model_validate({
        "active_flow": "ADVISORY_FLOW",
        "pending_question": "Q?",
        "return_to_flow": True,
    })
    assert state.active_flow == "ADVISORY_FLOW"
    assert not hasattr(state, "return_to_flow")


def test_flow_state_equality():
    a = FlowState(active_flow="ADVISORY_FLOW", pending_question="Q?")
    b = FlowState(active_flow="ADVISORY_FLOW", pending_question="Q?")
    assert a == b
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/services/chat/test_flow_state_model.py -v`
Expected: `ImportError: cannot import name 'FlowState' from 'services.chat.models'`

- [ ] **Step 3: Add FlowState to models.py**

Open `services/chat/models.py`. After the `ChatProfileState` class (ends at line 33), add:

```python
class FlowState(BaseModel):
    active_flow: Optional[str] = None       # "ADVISORY_FLOW" khi đang trong luồng tư vấn
    pending_question: Optional[str] = None  # follow-up question cuối cùng đã hỏi user
```

`Optional` is already imported at the top of `models.py` (line 1) — no new imports needed. Pydantic v2 `BaseModel` ignores unknown keys by default, so legacy `return_to_flow` in old JSON is dropped silently (covered by the test above).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/services/chat/test_flow_state_model.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add services/chat/models.py tests/services/chat/test_flow_state_model.py
git commit -m "feat: add FlowState model to services/chat/models"
```

---

### Task 2: DB Migration

**Files:**
- Create: `db/migrations/012_flow_state.sql`

- [ ] **Step 1: Create migration file**

Create `db/migrations/012_flow_state.sql`:

```sql
-- Add flow control state column to chat_sessions.
-- Kept separate from profile_state_json: profile data vs. routing state are different concerns.
ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS flow_state_json JSONB NOT NULL DEFAULT '{}';
```

`012` is the next number — the highest existing migration is `011_advisory_trace_events.sql`.

- [ ] **Step 2: Apply the migration twice to prove idempotency**

Run:
```bash
psql $DATABASE_URL -f db/migrations/012_flow_state.sql
psql $DATABASE_URL -f db/migrations/012_flow_state.sql
```
Expected: No error on the second run (`ADD COLUMN IF NOT EXISTS` is a no-op when the column exists).

- [ ] **Step 3: Verify the column exists with the right type and default**

Run: `psql $DATABASE_URL -c "\d chat_sessions"`
Expected: a `flow_state_json` row of type `jsonb`, `not null`, default `'{}'::jsonb`.

- [ ] **Step 4: Commit**

```bash
git add db/migrations/012_flow_state.sql
git commit -m "feat: add flow_state_json column to chat_sessions"
```

---

### Task 3: Repository — get_flow_state

**Files:**
- Modify: `services/chat/repository.py` (import line 5; new method after `get_profile_state`, line 116)
- Test: `tests/services/chat/test_repository.py`

- [ ] **Step 1: Create test file and write failing tests**

Create `tests/services/chat/test_repository.py`:

```python
from unittest.mock import MagicMock

from services.chat.repository import ChatSessionRepository
from services.chat.models import FlowState


def _make_conn(fetchone_return=None):
    """Returns (conn, cursor) MagicMocks wired together. Cursor returns tuples (like psycopg2)."""
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_return
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def test_get_flow_state_returns_default_when_column_is_null():
    conn, _ = _make_conn(fetchone_return=(None,))   # row exists, column value is NULL
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    result = repo.get_flow_state("tok-1")

    assert result == FlowState()
    assert result.active_flow is None
    assert result.pending_question is None


def test_get_flow_state_returns_default_when_row_missing():
    conn, _ = _make_conn(fetchone_return=None)   # no session row at all
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    result = repo.get_flow_state("tok-1")

    assert result == FlowState()


def test_get_flow_state_returns_persisted_state():
    saved = {"active_flow": "ADVISORY_FLOW", "pending_question": "Bạn học khối gì?"}
    conn, _ = _make_conn(fetchone_return=(saved,))
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    result = repo.get_flow_state("tok-1")

    assert result.active_flow == "ADVISORY_FLOW"
    assert result.pending_question == "Bạn học khối gì?"


def test_get_flow_state_queries_correct_table_and_token():
    conn, cursor = _make_conn(fetchone_return=(None,))
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    repo.get_flow_state("my-token")

    sql = cursor.execute.call_args[0][0]
    params = cursor.execute.call_args[0][1]
    assert "flow_state_json" in sql
    assert "chat_sessions" in sql
    assert params == ("my-token",)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/services/chat/test_repository.py -v`
Expected: `AttributeError: 'ChatSessionRepository' object has no attribute 'get_flow_state'`

- [ ] **Step 3: Add the import and get_flow_state to repository.py**

Open `services/chat/repository.py`. Change the model import on line 5 to add `FlowState`:

```python
from services.chat.models import ChatSessionRecord, ChatMessageRecord, ChatProfileState, FlowState
```

Then add `get_flow_state` immediately after `get_profile_state` (after line 116):

```python
    def get_flow_state(self, session_token: str) -> FlowState:
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            "SELECT flow_state_json FROM chat_sessions WHERE session_token = %s",
            (session_token,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return FlowState()
        return FlowState(**(row[0] or {}))
```

This mirrors `get_profile_state`'s tuple-cursor style (`row[0]`, not `row["..."]`) and `ChatProfileState(**...)` construction.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/services/chat/test_repository.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add services/chat/repository.py tests/services/chat/test_repository.py
git commit -m "feat: add get_flow_state to ChatSessionRepository"
```

---

### Task 4: Repository — update_flow_state

**Files:**
- Modify: `services/chat/repository.py` (new method after `get_flow_state`)
- Test: `tests/services/chat/test_repository.py` (extend)

- [ ] **Step 1: Add failing tests**

Append to `tests/services/chat/test_repository.py`:

```python
def test_update_flow_state_executes_update_sql_and_commits():
    conn, cursor = _make_conn()
    repo = ChatSessionRepository(connection_factory=lambda: conn)
    flow = FlowState(active_flow="ADVISORY_FLOW", pending_question="Q?")

    repo.update_flow_state("tok-1", flow)

    cursor.execute.assert_called_once()
    sql = cursor.execute.call_args[0][0]
    assert "flow_state_json" in sql
    assert "chat_sessions" in sql
    conn.commit.assert_called_once()


def test_update_flow_state_wraps_value_with_jsonb_helper():
    """Must use self._jsonb(...) like every other write, not a raw model_dump_json string."""
    conn, cursor = _make_conn()
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    repo.update_flow_state("tok-1", FlowState(active_flow="ADVISORY_FLOW"))

    first_param = cursor.execute.call_args[0][1][0]
    # psycopg2.extras.Json wraps the dict; its .adapted attribute holds the original value
    assert getattr(first_param, "adapted", None) == {
        "active_flow": "ADVISORY_FLOW",
        "pending_question": None,
    }


def test_update_flow_state_passes_correct_session_token():
    conn, cursor = _make_conn()
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    repo.update_flow_state("specific-token", FlowState())

    params = cursor.execute.call_args[0][1]
    assert "specific-token" in params


def test_update_flow_state_closes_connection():
    conn, cursor = _make_conn()
    repo = ChatSessionRepository(connection_factory=lambda: conn)

    repo.update_flow_state("tok-1", FlowState())

    assert cursor.close.called
    assert conn.close.called
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `pytest tests/services/chat/test_repository.py::test_update_flow_state_executes_update_sql_and_commits -v`
Expected: `AttributeError: 'ChatSessionRepository' object has no attribute 'update_flow_state'`

- [ ] **Step 3: Add update_flow_state to repository.py**

Add this method immediately after `get_flow_state`:

```python
    def update_flow_state(self, session_token: str, flow_state: FlowState) -> None:
        conn = self.connection_factory()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE chat_sessions
            SET flow_state_json = %s, updated_at = NOW()
            WHERE session_token = %s
            """,
            (self._jsonb(flow_state), session_token),
        )
        conn.commit()
        cur.close()
        conn.close()
```

`self._jsonb` (defined at line 12) wraps `jsonable_encoder(value)` in `psycopg2.extras.Json` — same as `update_profile_state`. DB failures propagate (no try/except), per spec §4.

- [ ] **Step 4: Run all repository tests**

Run: `pytest tests/services/chat/test_repository.py -v`
Expected: 8 passed

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `pytest --tb=short -q`
Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add services/chat/repository.py tests/services/chat/test_repository.py
git commit -m "feat: add update_flow_state to ChatSessionRepository"
```

---

## Plan 1 done — exit criteria

- `FlowState` importable from `services.chat.models` with two fields, ignores legacy `return_to_flow`.
- Migration `012_flow_state.sql` applies idempotently; `flow_state_json JSONB NOT NULL DEFAULT '{}'` exists.
- `repo.get_flow_state` / `repo.update_flow_state` round-trip via the tuple-cursor + `_jsonb` pattern.
- 14 new tests pass (6 model + 8 repository); no regressions.

**Next:** Plan 2 (IntentRouter) depends on `FlowState` and `ChatProfileState` being available.
