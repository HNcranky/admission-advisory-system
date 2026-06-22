# P0 — Retire Debug Panel + Simplify agent_tracer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the in-app agent trace viewer (debug panel) and collapse tracing onto a single sink (Langfuse), leaving `agent_tracer.traced` as a thin Langfuse-only decorator.

**Architecture:** `agent_tracer.traced` currently does double duty — writes per-stage events to `TraceRepository` (read by the `/trace` endpoint → right-column UI) **and** opens a Langfuse `stage_span`. We drop the `TraceRepository` half everywhere, delete the read path (endpoint + service + repository + UI), and keep the Langfuse span half. The `advisory_trace_events` table is left dormant (no migration to drop). No LangGraph work here — this phase is independent and unblocks a clean decorator for P1–P3.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, vanilla JS (ES modules), Langfuse v3 (OTEL seam in `observability/run_trace.py`), pytest, Postgres.

## Global Constraints

- **Never run `git push`.** Commit only.
- **No `Co-Authored-By` / AI attribution** in commit messages.
- Pydantic is **v2** (`model_config = ConfigDict(...)`).
- Run tests with `.\.venv\Scripts\python.exe -m pytest` (auto-redirects to `admission_test` DB via `tests/conftest.py`).
- Langfuse is wired via the **custom OTEL seam** (`observability/run_trace.py`); **do NOT** introduce `langfuse.langchain.CallbackHandler`.
- Source of truth: `docs/superpowers/specs/2026-06-18-langgraph-agentization-design.md` §6.5, §8 (Phase 0).

---

## File Structure

**Modify**
- `services/tracing/agent_tracer.py` — drop `TraceRepository` writes + `STAGE_ORDER`; keep `stage_span`/extractor wiring.
- `web/routes/chat_api.py` — remove `/trace` endpoint + `get_trace_service` + import.
- `web/routes/pages.py` — drop `STAGE_LABELS`, `stage_labels`, `debug_ui_enabled` from the template context.
- `web/templates/chat.html` — remove the right-column `<aside id="trace-panel">`, the `open-right-drawer` header button.
- `web/static/js/chat.js` — remove all `trace.js` imports + calls.
- `web/static/js/modules/layout.js` — remove right-panel (`trace-panel`) wiring.
- `web/static/css/chat.css` — collapse `.grid-3col` to two columns.

**Delete**
- `services/tracing/trace_service.py`
- `services/tracing/trace_repository.py`
- `web/static/js/modules/trace.js`
- `tests/web/test_trace_endpoint_integration.py`
- `tests/services/tracing/test_trace_service.py`
- `tests/services/tracing/test_trace_repository.py`
- `tests/services/tracing/test_trace_repository_integration.py`

**Leave as-is (dormant)**
- `db/migrations/011_advisory_trace_events.sql` — table stays; we simply stop writing to it. (A drop migration `014` is optional future cleanup, out of scope.)
- `services/tracing/extractors.py` — still feeds Langfuse span input/output. **Keep.**
- `observability/run_trace.py` — unchanged in P0.

---

### Task 1: Simplify `agent_tracer.traced` to Langfuse-only

**Files:**
- Modify: `services/tracing/agent_tracer.py`
- Test: `tests/services/tracing/test_agent_tracer_langfuse.py` (update), `tests/services/tracing/test_agent_tracer.py` (if present — update/remove repo assertions)

**Interfaces:**
- Produces: `traced(stage: str, sequence: int, output_extractor: Callable, input_extractor: Callable | None = None)` — decorator unchanged in signature **except** the `repository` parameter is removed. Still returns a wrapper `(state) -> result` that opens a `stage_span` and calls `set_span_output`. No DB writes.
- Consumed by: `graph.py` (calls `traced("profile", 0, extract_profile, input_profile)` — already passes no repository, so compatible).

- [ ] **Step 1: Update the tracer unit test to assert Langfuse-only behavior**

Replace the body of `tests/services/tracing/test_agent_tracer_langfuse.py` with assertions that `traced` opens a span and sets output but never touches a repository. Use a fake span recorder.

```python
import types

from services.tracing import agent_tracer


def test_traced_opens_span_and_sets_output_without_repository(monkeypatch):
    calls = {"span_opened": False, "output": None}

    class FakeSpanCM:
        def __enter__(self): return "SPAN"
        def __exit__(self, *a): return False

    def fake_stage_span(stage, sequence, input_json=None):
        calls["span_opened"] = (stage, sequence, input_json)
        return FakeSpanCM()

    def fake_set_span_output(span, output_json):
        calls["output"] = (span, output_json)

    monkeypatch.setattr(agent_tracer, "stage_span", fake_stage_span)
    monkeypatch.setattr(agent_tracer, "set_span_output", fake_set_span_output)

    state = types.SimpleNamespace(trace_run_id=7, value=1)
    wrapped = agent_tracer.traced(
        "profile", 0,
        output_extractor=lambda result, st: {"out": result.value},
        input_extractor=lambda st: {"in": st.value},
    )(lambda st: types.SimpleNamespace(value=st.value + 1))

    result = wrapped(state)

    assert result.value == 2
    assert calls["span_opened"] == ("profile", 0, {"in": 1})
    assert calls["output"] == ("SPAN", {"out": 2})


def test_traced_noop_when_no_run_id(monkeypatch):
    monkeypatch.setattr(agent_tracer, "stage_span",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not span")))
    state = types.SimpleNamespace(trace_run_id=None)
    wrapped = agent_tracer.traced("profile", 0, lambda r, s: {})(lambda st: "ok")
    assert wrapped(state) == "ok"
```

- [ ] **Step 2: Run the test — expect failure**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/tracing/test_agent_tracer_langfuse.py -v`
Expected: FAIL (current `traced` still imports/calls `TraceRepository`; `agent_tracer` has no `stage_span` attribute to patch at module level — `AttributeError` or repo write assertion mismatch).

- [ ] **Step 3: Rewrite `services/tracing/agent_tracer.py`**

```python
import logging
from typing import Callable

from observability.run_trace import stage_span, set_span_output

logger = logging.getLogger(__name__)


def traced(stage: str, sequence: int, output_extractor: Callable,
           input_extractor: Callable | None = None):
    """Wrap a graph node so it emits one Langfuse stage span.

    The span's input is `input_extractor(state)` and its output is
    `output_extractor(result, state)`. No-ops (runs the node bare) when the
    state carries no `trace_run_id`, i.e. outside a traced run.
    """
    def decorator(agent_fn):
        def wrapped(state):
            run_id = getattr(state, "trace_run_id", None)
            if run_id is None:
                return agent_fn(state)
            input_json = None
            if input_extractor is not None:
                try:
                    input_json = input_extractor(state)
                except Exception as exc:
                    logger.warning("trace input extractor failed for stage=%s: %r", stage, exc)
                    input_json = {"_extractor_error": repr(exc)}
            with stage_span(stage, sequence, input_json=input_json) as span:
                result = agent_fn(state)
                try:
                    output_json = output_extractor(result, state)
                except Exception as exc:
                    logger.warning("trace extractor failed for stage=%s: %r", stage, exc)
                    output_json = {"_extractor_error": repr(exc)}
                set_span_output(span, output_json)
            return result

        return wrapped

    return decorator
```

Note: `STAGE_ORDER`, `TraceRepository`, `_default_repo`, `_safe`, and the `repository` parameter are all gone. (`STAGE_ORDER`'s only consumer, `trace_service.py`, is deleted in Task 2 — if any test still imports it before Task 2 lands, run Task 2 in the same change set.)

- [ ] **Step 4: Run the test — expect pass**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/tracing/test_agent_tracer_langfuse.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/tracing/agent_tracer.py tests/services/tracing/test_agent_tracer_langfuse.py
git commit -m "refactor(tracing): make agent_tracer Langfuse-only, drop TraceRepository writes"
```

---

### Task 2: Remove the backend trace read-path

**Files:**
- Modify: `web/routes/chat_api.py:1-45`
- Delete: `services/tracing/trace_service.py`, `services/tracing/trace_repository.py`
- Delete: `tests/web/test_trace_endpoint_integration.py`, `tests/services/tracing/test_trace_service.py`, `tests/services/tracing/test_trace_repository.py`, `tests/services/tracing/test_trace_repository_integration.py`
- Modify (if it asserts DB events): `tests/services/tracing/test_graph_tracing_integration.py`

**Interfaces:**
- Removes: `GET /api/sessions/{session_token}/trace` and `services.tracing.trace_service.TraceService`.
- The advisory pipeline (`graph.py`) keeps tracing via Task 1's `traced` → Langfuse spans only.

- [ ] **Step 1: Delete the trace read-path modules and their tests**

```bash
git rm services/tracing/trace_service.py services/tracing/trace_repository.py
git rm tests/web/test_trace_endpoint_integration.py
git rm tests/services/tracing/test_trace_service.py
git rm tests/services/tracing/test_trace_repository.py
git rm tests/services/tracing/test_trace_repository_integration.py
```

- [ ] **Step 2: Remove the endpoint from `web/routes/chat_api.py`**

Delete the `TraceService` import (line 6), the `get_trace_service` factory (lines 19-20), and the `get_trace` route (lines 40-45). Final file:

```python
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from services.chat.conversation_service import ConversationService
from services.chat.session_service import AnonymousSessionService

router = APIRouter(prefix="/api/sessions", tags=["chat"])

class ChatMessageCreate(BaseModel):
    content: str = Field(max_length=4000)

def get_session_service():
    return AnonymousSessionService()

def get_conversation_service():
    return ConversationService()

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
    service.start_run(session_token, payload.content, result)
    return result.model_dump()
```

- [ ] **Step 3: Fix the graph tracing integration test**

Open `tests/services/tracing/test_graph_tracing_integration.py`. If it asserts `advisory_trace_events` rows / `TraceRepository` calls, rewrite those assertions to verify Langfuse `stage_span` is invoked per stage instead (patch `services.tracing.agent_tracer.stage_span` with a recorder and assert 6 stage names appear). If the file's sole purpose was DB-event verification, delete it: `git rm tests/services/tracing/test_graph_tracing_integration.py`.

```python
# Example replacement assertion (only if the file is kept):
def test_graph_emits_one_stage_span_per_node(monkeypatch):
    seen = []
    import contextlib
    @contextlib.contextmanager
    def fake_stage_span(stage, sequence, input_json=None):
        seen.append(stage)
        yield "SPAN"
    monkeypatch.setattr("services.tracing.agent_tracer.stage_span", fake_stage_span)
    monkeypatch.setattr("services.tracing.agent_tracer.set_span_output", lambda *a, **k: None)
    # ... build minimal AgentState with trace_run_id set, invoke graph, assert:
    assert seen == ["profile", "retrieve", "conflict", "reason", "policy", "explain"]
```

- [ ] **Step 4: Run the tracing + web test suites — expect pass / no import errors**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/tracing tests/web -q`
Expected: PASS, no `ModuleNotFoundError: services.tracing.trace_service`.

- [ ] **Step 5: Commit**

```bash
git add web/routes/chat_api.py tests/services/tracing/test_graph_tracing_integration.py
git commit -m "refactor(web): remove /trace endpoint and TraceRepository read-path"
```

---

### Task 3: Frontend teardown of the trace panel

**Files:**
- Delete: `web/static/js/modules/trace.js`
- Modify: `web/static/js/chat.js`, `web/static/js/modules/layout.js`, `web/templates/chat.html`, `web/routes/pages.py`, `web/static/css/chat.css`

**Interfaces:**
- Removes all DOM/JS dependence on `#trace-panel`, `#trace-cards`, `open-right-drawer`, `collapse-right`. The chat layout becomes two columns (profile | chat).

- [ ] **Step 1: Delete the trace module**

```bash
git rm web/static/js/modules/trace.js
```

- [ ] **Step 2: Remove trace usage from `web/static/js/chat.js`**

Remove the `trace.js` import block (lines 11-16), the `traceOpts` helper (lines 59-62), the two `stopTracePolling()` calls inside the poll-status handler (lines 282, 288), the debug panel reveal (lines 358-362), the `startTracePolling(...)` call in the bootstrap block (lines 367-369), the `startTracePolling(...)` call after reset (line 411), and the `stopTracePolling()` in the reset handler (line 427). Concretely:

- Delete:
```javascript
import {
  renderTrace,
  startTracePolling,
  stopTracePolling,
  debugUiEnabled,
} from "./modules/trace.js";
```
- Delete the `traceOpts` const.
- Delete each `stopTracePolling();` and `startTracePolling(...);` line.
- Delete the block:
```javascript
  if (debugUiEnabled()) {
    const panel = document.getElementById("trace-panel");
    if (panel) panel.hidden = false;
  }
```
- Delete the `if (debugUiEnabled() && ...) { startTracePolling(...); }` guard around bootstrap.

After editing, grep to confirm zero references remain:

Run: `.\.venv\Scripts\python.exe -c "import pathlib,sys; t=pathlib.Path('web/static/js/chat.js').read_text(encoding='utf-8'); sys.exit('trace' in t.lower() and 'FOUND' or 'CLEAN')"`
Expected: prints/raises `CLEAN`.

- [ ] **Step 3: Remove right-panel wiring from `web/static/js/modules/layout.js`**

- In `applyCollapsed`, delete the `rightPanel` lookup + `setAttribute` (lines 33, 35).
- In `wireCollapseButton`, it is called for both sides; remove the `"right"` call (see Step below) — keep the function generic but it will no longer find `collapse-right`.
- Replace `panelIdForSide` body to only handle the left/profile panel:
```javascript
function panelIdForSide(side) {
  return "profile-panel";
}
```
- In `wireDrawerDismiss`, change the panel list to `["profile-panel"]`.
- In `initCollapseHandles`, delete `wireCollapseButton(shell, state, "right");` and `wireDrawerButton("right");`.

(The `right` key in persisted layout state is now inert; leave the state shape unchanged to avoid breaking stored localStorage.)

- [ ] **Step 4: Remove the trace panel from `web/templates/chat.html`**

- Delete the `open-right-drawer` header button (lines 73-81).
- Delete the entire `<aside class="panel panel--side panel--right" id="trace-panel" ...> ... </aside>` block (lines 159-194).
- Change `<main class="grid-3col">` to `<main class="grid-2col">`.

- [ ] **Step 5: Drop trace context from `web/routes/pages.py`**

- Delete the `STAGE_LABELS` constant (lines 31-38).
- Delete `"debug_ui_enabled": _debug_ui_enabled(),` and `"stage_labels": STAGE_LABELS,` from the template context.
- Delete the now-unused `_debug_ui_enabled` helper (lines 41-42).

Final context dict:
```python
        {
            "page_title": "Student Advisory Chat",
            "theme_default": _theme_default(),
            "app_version": _APP_VERSION,
        },
```

- [ ] **Step 6: Collapse the grid to two columns in `web/static/css/chat.css`**

Add a `.grid-2col` rule next to `.grid-3col` (line 171) reusing the left + center tracks:
```css
.grid-2col {
  display: grid;
  grid-template-columns: var(--col-left) minmax(0, 1fr);
}
```
And in the mobile breakpoint (line 515-518) add `.grid-2col` alongside `.grid-3col`:
```css
@media (max-width: 899px) {
  .grid-3col,
  .grid-2col {
    grid-template-columns: minmax(0, 1fr);
  }
```
(The now-dead `#trace-panel` / `.right-collapsed` / `.panel--right` rules are harmless leftovers; removing them is optional cleanup, not required.)

- [ ] **Step 7: Smoke-test the page renders without the panel**

Run: `.\.venv\Scripts\python.exe -m pytest tests/web -q`
Then manually: `.\.venv\Scripts\python.exe -m uvicorn web.app:app` and load `/` — confirm two columns, no JS console error, chat still sends/receives.
Expected: page renders; no reference errors for `trace-panel` / `startTracePolling`.

- [ ] **Step 8: Commit**

```bash
git add web/ 
git commit -m "refactor(web): tear down agent trace viewer UI (panel, JS, template, css)"
```

---

### Task 4: Document the retirement

**Files:**
- Modify: `CLAUDE.md` (the `services/tracing/` bullet), `QUICKSTART.md` if it mentions the debug panel / `ADVISORY_DEBUG_UI`.

- [ ] **Step 1: Update the architecture note**

In `CLAUDE.md`, change the `services/tracing/` description from "per-stage trace events for the debug panel" to: "per-stage Langfuse spans (`agent_tracer.traced` → `stage_span`); the in-app trace viewer was retired in favour of Langfuse (spec 2026-06-18)."

- [ ] **Step 2: Note the dormant table**

Append a line under the migrations note: "`011_advisory_trace_events` is dormant after 2026-06-18 (no longer written); drop via a future migration if desired."

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md QUICKSTART.md
git commit -m "docs: record debug-panel retirement and dormant trace table"
```

---

## Self-Review (P0)

- **Spec coverage:** spec §6.5 "Retire panel — xóa" list → Tasks 2 (backend) + 3 (frontend); "Gọn agent_tracer" → Task 1; "bảng 011 dormant" → Task 4. ✓
- **Placeholder scan:** none — every code change shows code; deletions name exact paths/lines.
- **Type consistency:** `traced(stage, sequence, output_extractor, input_extractor)` signature matches `graph.py` call sites (no `repository` arg). ✓
- **Risk:** the only behavioral change for end users is the (already-hidden) right column disappearing; advisory tracing continues via Langfuse spans (Task 1 test proves the span path).
