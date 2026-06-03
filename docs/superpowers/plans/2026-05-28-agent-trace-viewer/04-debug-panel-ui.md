# Slice 04 — Debug Panel UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the trace as 6 cards in the chat page, dev-only behind `?debug=1` or `ADVISORY_DEBUG_UI=1`. Each card shows status (pending / running with spinner / completed with duration / failed). Click toggles an expanded view that shows the stage's full `output_json` as pretty-printed JSON.

**Architecture:** Server reads the env flag once at startup and passes `debug_ui_enabled` into the Jinja template; the URL query param `?debug=1` can also force-enable client-side. The panel is rendered iff either is true. Polling the new `/trace` endpoint runs alongside the existing snapshot poll while the run is in `queued`/`running`. State of expanded cards is preserved across re-renders.

**Tech Stack:** Jinja2, vanilla JS, CSS, FastAPI Jinja templating.

---

### Task 1: Server-side debug flag wiring

**Files:**
- Modify: `web/routes/pages.py`
- Create: `tests/web/test_pages.py`

- [ ] **Step 1: Write the failing test**

```python
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from web.app import build_app


def test_chat_page_renders_debug_flag_true_when_env_set():
    with patch.dict(os.environ, {"ADVISORY_DEBUG_UI": "1"}):
        client = TestClient(build_app())
        response = client.get("/")
    assert response.status_code == 200
    assert 'data-debug-ui="true"' in response.text


def test_chat_page_renders_debug_flag_false_by_default():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ADVISORY_DEBUG_UI", None)
        client = TestClient(build_app())
        response = client.get("/")
    assert response.status_code == 200
    assert 'data-debug-ui="false"' in response.text
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/web/test_pages.py -v`
Expected: FAIL — current template has no `data-debug-ui` attribute.

- [ ] **Step 3: Wire the flag through `pages.py`**

Replace `web/routes/pages.py`:

```python
import os

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


def _debug_ui_enabled() -> bool:
    return os.environ.get("ADVISORY_DEBUG_UI") == "1"


@router.get("/")
def chat_page(request: Request):
    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "page_title": "Student Advisory Chat",
            "debug_ui_enabled": _debug_ui_enabled(),
        },
    )
```

- [ ] **Step 4: Render the flag in the template**

Edit `web/templates/chat.html`. Change the opening `<main class="chat-shell">` line to:

```html
<main class="chat-shell" data-debug-ui="{{ 'true' if debug_ui_enabled else 'false' }}">
```

- [ ] **Step 5: Run the test**

Run: `pytest tests/web/test_pages.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add web/routes/pages.py web/templates/chat.html tests/web/test_pages.py
git commit -m "feat(web): expose ADVISORY_DEBUG_UI flag to chat template"
```

---

### Task 2: Trace panel HTML markup (hidden by default)

**Files:**
- Modify: `web/templates/chat.html`

- [ ] **Step 1: Add the trace panel markup**

In `web/templates/chat.html`, immediately after the closing `</aside>` of the `summary-panel`, add a second `<aside>`:

```html
  <aside class="trace-panel" id="trace-panel" hidden>
    <h2>Trace</h2>
    <ol class="trace-cards" id="trace-cards">
      {% for stage in ["profile", "retrieve", "conflict", "reason", "policy", "explain"] %}
        <li class="trace-card trace-card--pending" data-stage="{{ stage }}" data-sequence="{{ loop.index0 }}">
          <button type="button" class="trace-card__header" aria-expanded="false">
            <span class="trace-card__icon" aria-hidden="true">○</span>
            <span class="trace-card__name">{{ stage }}</span>
            <span class="trace-card__meta">pending</span>
          </button>
          <pre class="trace-card__body" hidden></pre>
        </li>
      {% endfor %}
    </ol>
  </aside>
```

- [ ] **Step 2: Manual visual check**

Run uvicorn locally with the debug flag set:
```powershell
$env:ADVISORY_DEBUG_UI="1"
uvicorn web.app:build_app --factory --reload --port 8000
```
Open `http://127.0.0.1:8000/?debug=1` and inspect the DOM with devtools. Expected: `<aside id="trace-panel">` exists and contains 6 `<li>` cards. The panel is hidden because of the `hidden` attribute (will be unhidden by JS in Task 3).

Run the existing page test to confirm we didn't break templating:
```powershell
pytest tests/web/test_pages.py -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```powershell
git add web/templates/chat.html
git commit -m "feat(ui): add trace panel markup with 6 pending cards"
```

---

### Task 3: CSS for cards (pending / running / completed / failed)

**Files:**
- Modify: `web/static/css/chat.css`

- [ ] **Step 1: Append styles**

Append to `web/static/css/chat.css`:

```css
/* ===== Trace panel ===== */

.trace-panel {
  background: #fafafa;
  border-left: 1px solid #e5e7eb;
  padding: 1rem 1.25rem;
  min-width: 280px;
  max-width: 360px;
  overflow-y: auto;
}

.trace-panel h2 {
  margin: 0 0 0.75rem;
  font-size: 1rem;
  color: #374151;
}

.trace-cards {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.trace-card {
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  overflow: hidden;
}

.trace-card__header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: transparent;
  border: 0;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.trace-card__icon {
  display: inline-block;
  width: 1rem;
  text-align: center;
}

.trace-card__name {
  flex: 1;
  font-weight: 600;
  text-transform: capitalize;
}

.trace-card__meta {
  font-size: 0.85em;
  color: #6b7280;
  font-variant-numeric: tabular-nums;
}

.trace-card__body {
  margin: 0;
  padding: 0.75rem;
  background: #f9fafb;
  border-top: 1px solid #e5e7eb;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.8em;
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

/* Status variants */

.trace-card--pending   { background: #f9fafb; }
.trace-card--pending   .trace-card__icon { color: #9ca3af; }
.trace-card--pending   .trace-card__meta { color: #9ca3af; }

.trace-card--running   { background: #fffbeb; }
.trace-card--running   .trace-card__icon {
  color: #d97706;
  display: inline-block;
  animation: trace-spin 1s linear infinite;
}

.trace-card--completed { background: #f0fdf4; }
.trace-card--completed .trace-card__icon { color: #16a34a; }
.trace-card--completed .trace-card__meta { color: #166534; }

.trace-card--failed    { background: #fef2f2; }
.trace-card--failed    .trace-card__icon { color: #dc2626; }
.trace-card--failed    .trace-card__meta { color: #b91c1c; }

@keyframes trace-spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
```

- [ ] **Step 2: Manual visual check**

Reload `http://127.0.0.1:8000/?debug=1` in the browser. The 6 cards should now appear pending-styled, in a vertical stack. The panel itself is still `hidden` until Task 4 runs.

- [ ] **Step 3: Commit**

```powershell
git add web/static/css/chat.css
git commit -m "feat(ui): trace card styles with status variants and spinner keyframe"
```

---

### Task 4: JS — show panel when debug enabled

**Files:**
- Modify: `web/static/js/chat.js`

- [ ] **Step 1: Add debug detection + panel unhide**

At the top of `web/static/js/chat.js`, after the existing `const POLL_INTERVAL_MS = 1200;` line, add:

```javascript
const TRACE_POLL_INTERVAL_MS = 1000;
const TRACE_STAGES = ["profile", "retrieve", "conflict", "reason", "policy", "explain"];
let tracePollTimer = null;
const expandedStages = new Set();

function debugUiEnabled() {
  const fromTemplate = document.querySelector(".chat-shell")?.dataset.debugUi === "true";
  const fromUrl = new URLSearchParams(window.location.search).get("debug") === "1";
  return fromTemplate || fromUrl;
}

function showTracePanel() {
  const panel = document.getElementById("trace-panel");
  if (panel) panel.hidden = false;
}
```

Inside the `DOMContentLoaded` handler, at the top of the body (before the `try`), add:

```javascript
  if (debugUiEnabled()) {
    showTracePanel();
  }
```

- [ ] **Step 2: Manual check**

Reload `http://127.0.0.1:8000/?debug=1` and confirm the trace panel is now visible. Reload `http://127.0.0.1:8000/` (no `?debug=1`, env still set to `1`) — panel is still visible (template flag). Stop uvicorn, unset the env, restart, and reload `/` — panel is hidden; reload `/?debug=1` — panel reappears.

- [ ] **Step 3: Commit**

```powershell
git add web/static/js/chat.js
git commit -m "feat(ui): reveal trace panel when debug flag enabled"
```

---

### Task 5: JS — fetch + render trace events

**Files:**
- Modify: `web/static/js/chat.js`

- [ ] **Step 1: Add fetch + render**

Append to `web/static/js/chat.js`, after the `showTracePanel` function:

```javascript
async function fetchTrace(sessionToken) {
  const r = await fetch(`/api/sessions/${sessionToken}/trace`);
  if (!r.ok) throw new Error("trace fetch failed");
  return r.json();
}

function formatDuration(ms) {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function statusMeta(event) {
  switch (event.status) {
    case "completed": return formatDuration(event.duration_ms);
    case "running":   return "running…";
    case "failed":    return "failed";
    default:          return "pending";
  }
}

function statusIcon(status) {
  switch (status) {
    case "completed": return "●";
    case "running":   return "⟳";
    case "failed":    return "✕";
    default:          return "○";
  }
}

function renderTraceCards(events) {
  const root = document.getElementById("trace-cards");
  if (!root) return;
  events.forEach((event) => {
    const card = root.querySelector(`[data-stage="${event.stage}"]`);
    if (!card) return;

    card.classList.remove(
      "trace-card--pending",
      "trace-card--running",
      "trace-card--completed",
      "trace-card--failed",
    );
    card.classList.add(`trace-card--${event.status}`);

    card.querySelector(".trace-card__icon").textContent = statusIcon(event.status);
    card.querySelector(".trace-card__meta").textContent = statusMeta(event);

    const body = card.querySelector(".trace-card__body");
    if (event.status === "completed" && event.output_json) {
      body.textContent = JSON.stringify(event.output_json, null, 2);
    } else if (event.status === "failed") {
      body.textContent = event.error_text || "(no error text)";
    } else {
      body.textContent = "";
    }

    // Restore expanded state
    const isExpanded = expandedStages.has(event.stage);
    body.hidden = !isExpanded;
    card.querySelector(".trace-card__header").setAttribute("aria-expanded", String(isExpanded));
  });
}
```

- [ ] **Step 2: Manual check (no polling yet)**

Open devtools console on `/?debug=1`, paste:
```javascript
fetchTrace(currentSessionToken).then(p => renderTraceCards(p.events));
```
Expected: cards remain pending (no run started yet). No errors.

- [ ] **Step 3: Commit**

```powershell
git add web/static/js/chat.js
git commit -m "feat(ui): trace fetch + per-card render"
```

---

### Task 6: JS — click handler to expand/collapse

**Files:**
- Modify: `web/static/js/chat.js`

- [ ] **Step 1: Wire click handlers once on DOM ready**

Inside the `DOMContentLoaded` handler, after the `if (debugUiEnabled())` block, add:

```javascript
  document.querySelectorAll("#trace-cards .trace-card").forEach((card) => {
    const header = card.querySelector(".trace-card__header");
    header.addEventListener("click", () => {
      const stage = card.dataset.stage;
      const body = card.querySelector(".trace-card__body");
      const expanded = expandedStages.has(stage);
      if (expanded) {
        expandedStages.delete(stage);
        body.hidden = true;
        header.setAttribute("aria-expanded", "false");
      } else {
        expandedStages.add(stage);
        body.hidden = false;
        header.setAttribute("aria-expanded", "true");
      }
    });
  });
```

- [ ] **Step 2: Manual check**

Reload `/?debug=1`. Click each card header — it should toggle the `<pre>` underneath. For `pending` cards the body is empty (visible but blank). For a `completed` card (after a run) the pretty JSON appears.

- [ ] **Step 3: Commit**

```powershell
git add web/static/js/chat.js
git commit -m "feat(ui): expand/collapse trace cards on click"
```

---

### Task 7: JS — polling lifecycle

**Files:**
- Modify: `web/static/js/chat.js`

- [ ] **Step 1: Add polling functions**

Append to `web/static/js/chat.js`:

```javascript
function stopTracePolling() {
  if (tracePollTimer) {
    window.clearTimeout(tracePollTimer);
    tracePollTimer = null;
  }
}

function startTracePolling(sessionToken) {
  if (!debugUiEnabled()) return;
  stopTracePolling();

  const tick = async () => {
    try {
      const payload = await fetchTrace(sessionToken);
      renderTraceCards(payload.events);
      if (payload.run_status === "running" || payload.run_status === "queued") {
        tracePollTimer = window.setTimeout(tick, TRACE_POLL_INTERVAL_MS);
      }
    } catch (e) {
      // trace fetch failures must not interfere with the chat UX
      tracePollTimer = window.setTimeout(tick, TRACE_POLL_INTERVAL_MS * 2);
    }
  };

  tick();
}
```

- [ ] **Step 2: Hook into the existing send flow**

In `web/static/js/chat.js`, find the `form.addEventListener("submit", ...)` block. Right after the line:
```javascript
        schedulePolling(currentSessionToken);
```
add:
```javascript
        startTracePolling(currentSessionToken);
```

Also in `schedulePolling`, where the run reaches a terminal status, stop trace polling. Update the two terminal branches:

Find:
```javascript
    if (snapshot.session.status === "completed") {
      setStatus("Đã có kết quả tư vấn.", "success");
      stopPolling();
      return;
    }
    if (snapshot.session.status === "failed") {
      setStatus("Quá trình phân tích bị gián đoạn.", "error");
      stopPolling();
      return;
    }
```
Replace with:
```javascript
    if (snapshot.session.status === "completed") {
      setStatus("Đã có kết quả tư vấn.", "success");
      stopPolling();
      // do one last trace fetch so the final stage flips to completed instantly
      if (debugUiEnabled()) {
        fetchTrace(sessionToken).then((p) => renderTraceCards(p.events)).catch(() => {});
        stopTracePolling();
      }
      return;
    }
    if (snapshot.session.status === "failed") {
      setStatus("Quá trình phân tích bị gián đoạn.", "error");
      stopPolling();
      if (debugUiEnabled()) {
        fetchTrace(sessionToken).then((p) => renderTraceCards(p.events)).catch(() => {});
        stopTracePolling();
      }
      return;
    }
```

- [ ] **Step 3: Hook into reset / bootstrap**

In the reset button handler, after `stopPolling();`, add:
```javascript
    stopTracePolling();
```

In bootstrap (after `renderSnapshot(bootstrap)`), if a run is already in-flight when the page loads, start trace polling:
```javascript
    if (debugUiEnabled() && bootstrap.session && bootstrap.session.status === "running") {
      startTracePolling(currentSessionToken);
    }
```

- [ ] **Step 4: Manual end-to-end check**

Bring up the full stack:
```powershell
docker compose up -d --wait db
$env:GEMINI_API_KEY=<your key>
$env:ADVISORY_DEBUG_UI="1"
uvicorn web.app:build_app --factory --reload --port 8000
```
Open `http://127.0.0.1:8000/?debug=1`. Send a message that triggers a run (e.g., a complete profile). Watch the trace panel:

- All 6 cards start `pending` (grey ○).
- As stages run, each flips: yellow spinner ⟳ → green ● with `1.2s`-style duration.
- Click any completed card → expands to show pretty JSON of that stage's output.
- Refreshing the page mid-run preserves trace visibility (DB-backed).

- [ ] **Step 5: Commit**

```powershell
git add web/static/js/chat.js
git commit -m "feat(ui): live trace polling with terminal-state final fetch"
```

---

### Task 8: Documentation update

**Files:**
- Modify: `QUICKSTART.md`

- [ ] **Step 1: Add a "Trace viewer" section**

In `QUICKSTART.md`, after section "## 5. Run the chat web app", insert:

```markdown
### Optional: enable the trace viewer (dev-only)

Set the env flag before starting uvicorn:

```powershell
$env:ADVISORY_DEBUG_UI="1"
uvicorn web.app:build_app --factory --reload --port 8000
```

Then open `http://127.0.0.1:8000/?debug=1`. The right-hand "Trace" panel shows one card per agent stage; click a card to inspect its output JSON. Without the env flag, the panel is hidden. `?debug=1` alone also enables it client-side without restarting the server.
```

- [ ] **Step 2: Commit**

```powershell
git add QUICKSTART.md
git commit -m "docs: document trace viewer behind ADVISORY_DEBUG_UI / ?debug=1"
```

---

## Slice 04 Done When

- With `ADVISORY_DEBUG_UI=1` (or `?debug=1`), the chat page renders a Trace panel with 6 cards in stage order.
- Cards visibly transition pending → running (spinner) → completed (duration) live during a run.
- Clicking a card expands it inline to show pretty-printed JSON of the stage's output.
- Failed stages show error text on expand.
- Without the flag and without `?debug=1`, no panel renders — end-user chat is unaffected.
- `pytest -m "not integration"` and `pytest -m integration` (with docker DB up) both pass.
- Manual smoke against a live run succeeds.

This is the final slice. Once Slice 04 is done, the feature is complete and ready for review.
