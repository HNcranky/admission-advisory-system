# Slice 04 — Trace Panel Hybrid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the inline trace logic in `chat.js` with a dedicated `modules/trace.js` module, swap textual status glyphs (`○ ⟳ ● ✕`) for lucide SVG icons referenced via an inline `<symbol>` sprite, push Vietnamese stage labels from the server (`STAGE_LABELS`), keep JSON-body expansion gated behind debug mode, and add a 1px vertical connector line between trace cards for a timeline feel.

**Architecture:** The server (`web/routes/pages.py`) owns the canonical stage list (id, Vietnamese label, lucide icon name) as a module-level `STAGE_LABELS` and injects both `stage_labels` (Jinja-rendered card skeleton) and `window.__stageLabels` / `window.__debugUi` (client-readable globals) into `chat.html`. The template embeds an inline SVG sprite with 10 lucide `<symbol>` definitions (6 stage icons + 4 status icons) once near the top of `<body>`; cards use `<svg><use href="#icon-…"/></svg>` to reference them. A new ES module `web/static/js/modules/trace.js` exports `renderTrace`, `startTracePolling`, `stopTracePolling`, and `debugUiEnabled`; in end-user mode cards stay as non-clickable `<div>` rows and no JSON is injected into the DOM, while debug mode promotes each row to a `<button>` on first render and renders `output_json` / `error_text` into `.trace-card__body`.

**Tech Stack:** Jinja2 templating, FastAPI, vanilla JS ES modules (no bundler), CSS custom properties (tokens from slice 01), lucide MIT-licensed SVG paths inlined as `<symbol>` definitions.

---

### Task 1: Add `STAGE_LABELS` to `pages.py` and TDD Vietnamese labels rendering

**Files:**
- Modify: `web/routes/pages.py`
- Modify: `tests/web/test_pages.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/web/test_pages.py`:

```python
def test_chat_page_renders_vietnamese_stage_labels():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    for label in [
        "Phân tích hồ sơ",
        "Tra cứu chương trình",
        "Đối chiếu nguồn dữ liệu",
        "Suy luận khuyến nghị",
        "Đối chiếu quy chế",
        "Soạn lời giải thích",
    ]:
        assert label in response.text, f"missing stage label: {label}"
```

- [ ] **Step 2: Run to confirm failure**

```powershell
pytest tests/web/test_pages.py::test_chat_page_renders_vietnamese_stage_labels -v
```

Expected: FAIL — current template loops a list of raw English stage ids; no Vietnamese labels exist yet.

- [ ] **Step 3: Add `STAGE_LABELS` to `pages.py`**

Replace `web/routes/pages.py` with:

```python
import os

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


STAGE_LABELS: list[dict[str, str]] = [
    {"id": "profile",  "label": "Phân tích hồ sơ",         "icon": "user-circle"},
    {"id": "retrieve", "label": "Tra cứu chương trình",    "icon": "search"},
    {"id": "conflict", "label": "Đối chiếu nguồn dữ liệu", "icon": "git-compare"},
    {"id": "reason",   "label": "Suy luận khuyến nghị",    "icon": "lightbulb"},
    {"id": "policy",   "label": "Đối chiếu quy chế",       "icon": "shield-check"},
    {"id": "explain",  "label": "Soạn lời giải thích",     "icon": "message-square"},
]


def _debug_ui_enabled() -> bool:
    return os.environ.get("ADVISORY_DEBUG_UI") == "1"


def _theme_default() -> str:
    value = os.environ.get("ADVISORY_THEME_DEFAULT", "light").strip().lower()
    return value if value in {"light", "dark"} else "light"


@router.get("/")
def chat_page(request: Request):
    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "page_title": "Student Advisory Chat",
            "debug_ui_enabled": _debug_ui_enabled(),
            "theme_default": _theme_default(),
            "stage_labels": STAGE_LABELS,
        },
    )
```

> Note: `_theme_default()` was added in slice 01 — keep it. Only the `STAGE_LABELS` constant and the new `stage_labels` context key are introduced here. If slice 01 already added `theme_default` to the context, leave it untouched.

- [ ] **Step 4: Replace the trace-panel skeleton loop in `chat.html`**

In `web/templates/chat.html`, replace the existing `<ol class="trace-cards">` block (the one that currently iterates `["profile", "retrieve", "conflict", "reason", "policy", "explain"]`) with:

```html
<ol class="trace-cards" id="trace-cards">
  {% for stage in stage_labels %}
    <li class="trace-card trace-card--pending"
        data-stage="{{ stage.id }}"
        data-sequence="{{ loop.index0 }}">
      <div class="trace-card__row">
        <span class="trace-card__icon" aria-hidden="true">
          <svg class="icon icon--stage"><use href="#icon-{{ stage.icon }}"/></svg>
        </span>
        <span class="trace-card__name">{{ stage.label }}</span>
        <span class="trace-card__status" aria-hidden="true">
          <svg class="icon icon--status"><use href="#icon-status-pending"/></svg>
        </span>
        <span class="trace-card__meta">pending</span>
      </div>
      <pre class="trace-card__body" hidden></pre>
    </li>
  {% endfor %}
</ol>
```

> **Rationale for `<div class="trace-card__row">` (not `<button>`):** In end-user mode the cards are read-only; a non-interactive element avoids exposing a useless focus target and prevents screen readers from announcing six "buttons" that do nothing. In debug mode `trace.js` swaps the `<div>` for a `<button>` on first render (tracked via `dataset.debugWired`).

- [ ] **Step 5: Re-run the test**

```powershell
pytest tests/web/test_pages.py -v
```

Expected: all three `test_pages.py` tests PASS (the two existing `data-debug-ui` tests, plus the new Vietnamese-labels test).

- [ ] **Step 6: Commit**

```powershell
git add web/routes/pages.py web/templates/chat.html tests/web/test_pages.py
git commit -m @'
feat(web): push Vietnamese stage labels from server via STAGE_LABELS

Adds a module-level STAGE_LABELS list in pages.py and passes it as
stage_labels into the chat template. Replaces the hard-coded six-element
English stage loop in chat.html with a `{% for stage in stage_labels %}`
loop that renders each card with id, Vietnamese label, and lucide icon
slot. Card row is a `<div>` in end-user mode; debug mode upgrades it to
a `<button>` at JS render time.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 2: Add inline lucide SVG sprite block to `chat.html`

**Files:**
- Modify: `web/templates/chat.html`

**Rationale:** Browsers download the sprite once with the HTML, then any number of `<use href="#icon-…"/>` references re-render the same vector with zero additional requests. All paths are from lucide v0.469.0 (MIT license, https://github.com/lucide-icons/lucide). The sprite block sits at the very top of `<body>` with `width="0" height="0"` so it occupies no layout space.

- [ ] **Step 1: Insert sprite block at top of `<body>`**

In `web/templates/chat.html`, immediately after the opening `{% block body %}` line (i.e., before `<main class="chat-shell" …>`), insert:

```html
<svg width="0" height="0" style="position:absolute" aria-hidden="true" focusable="false">
  <defs>
    <!-- Stage icons (lucide v0.469.0, MIT) -->
    <symbol id="icon-user-circle" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M18 20a6 6 0 0 0-12 0"/>
      <circle cx="12" cy="10" r="4"/>
      <circle cx="12" cy="12" r="10"/>
    </symbol>
    <symbol id="icon-search" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="11" cy="11" r="8"/>
      <path d="m21 21-4.3-4.3"/>
    </symbol>
    <symbol id="icon-git-compare" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="5" cy="6" r="3"/>
      <path d="M12 6h5a2 2 0 0 1 2 2v7"/>
      <path d="M5 9v12"/>
      <circle cx="19" cy="18" r="3"/>
      <path d="M12 18H7a2 2 0 0 1-2-2V9"/>
      <path d="M19 15V3"/>
    </symbol>
    <symbol id="icon-lightbulb" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/>
      <path d="M9 18h6"/>
      <path d="M10 22h4"/>
    </symbol>
    <symbol id="icon-shield-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>
      <path d="m9 12 2 2 4-4"/>
    </symbol>
    <symbol id="icon-message-square" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
    </symbol>

    <!-- Status icons -->
    <symbol id="icon-status-pending" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="10"/>
    </symbol>
    <symbol id="icon-status-running" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
      <path d="M3 3v5h5"/>
      <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/>
      <path d="M16 16h5v5"/>
    </symbol>
    <symbol id="icon-status-completed" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="10"/>
      <path d="m9 12 2 2 4-4"/>
    </symbol>
    <symbol id="icon-status-failed" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="12" cy="12" r="10"/>
      <path d="m15 9-6 6"/>
      <path d="m9 9 6 6"/>
    </symbol>
  </defs>
</svg>
```

- [ ] **Step 2: Manual visual check**

```powershell
$env:ADVISORY_DEBUG_UI="1"
uvicorn web.app:build_app --factory --reload --port 8000
```

Open `http://127.0.0.1:8000/?debug=1`. Open devtools, inspect the DOM. Expected: the `<svg>` sprite block exists at the top of `<body>`. The trace cards already use `<use href="#icon-…"/>` and should render six stage icons + six pending-circle status icons. (CSS sizing in Task 7 may make them tiny/invisible until then — verify they exist via devtools, not by visual size.)

- [ ] **Step 3: Commit**

```powershell
git add web/templates/chat.html
git commit -m @'
feat(ui): add inline lucide SVG sprite for trace panel icons

Embeds a hidden `<svg>` block at the top of `<body>` with ten
`<symbol>` definitions: six stage icons (user-circle, search,
git-compare, lightbulb, shield-check, message-square) and four status
icons (pending circle, running refresh-cw arrows, completed check
circle, failed x-circle). Cards reference symbols via `<use
href="#icon-…"/>`, so the sprite downloads once and any number of
icon instances re-render at zero additional cost.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 3: Inject `window.__stageLabels` and `window.__debugUi` globals into `chat.html`

**Files:**
- Modify: `web/templates/chat.html`
- Modify: `tests/web/test_pages.py`

**Rationale:** The new `trace.js` needs the same `stage_labels` list the server used to build the skeleton, plus the debug flag. We could read these by parsing data-attributes off the DOM, but a tiny explicit `<script>` block keeps the contract obvious and trivial to assert in tests. The script must appear *before* `chat.js` is loaded.

- [ ] **Step 1: Write the failing test**

Append to `tests/web/test_pages.py`:

```python
def test_chat_page_exposes_stage_labels_and_debug_globals():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "window.__stageLabels" in response.text
    assert "window.__debugUi" in response.text


def test_chat_page_renders_svg_sprite():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert '<symbol id="icon-user-circle"' in response.text
    assert '<symbol id="icon-status-pending"' in response.text
```

- [ ] **Step 2: Run to confirm failure**

```powershell
pytest tests/web/test_pages.py::test_chat_page_exposes_stage_labels_and_debug_globals tests/web/test_pages.py::test_chat_page_renders_svg_sprite -v
```

Expected: the `stage_labels`/`__debugUi` test FAILs; the sprite test should already PASS after Task 2 (kept here so the full suite covers it).

- [ ] **Step 3: Add the globals block**

In `web/templates/chat.html`, find the existing `<script type="module" src="…/chat.js"></script>` (or equivalent) tag. Immediately *before* it, insert:

```html
<script>
  window.__stageLabels = {{ stage_labels | tojson }};
  window.__debugUi = {{ 'true' if debug_ui_enabled else 'false' }};
</script>
```

> If `chat.js` is loaded from `base.html` rather than `chat.html`, place the block in the `{% block body %}` near the bottom (after `</main>`) so it runs before any deferred module fetch resolves. The DOMContentLoaded handler in `chat.js` only fires after the page is fully parsed, so order of execution is guaranteed.

- [ ] **Step 4: Re-run the test**

```powershell
pytest tests/web/test_pages.py -v
```

Expected: all `test_pages.py` tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add web/templates/chat.html tests/web/test_pages.py
git commit -m @'
feat(ui): expose stage_labels and debug_ui flag to client via globals

Adds a small inline `<script>` block in chat.html that sets
`window.__stageLabels` (the same Vietnamese-labeled list the server
used to render the trace skeleton) and `window.__debugUi` (the
ADVISORY_DEBUG_UI boolean). The new trace.js module reads these to
drive debug-only DOM upgrades without re-parsing data-attributes.

Tests assert both globals and the SVG sprite are present in the
rendered HTML.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 4: Create `web/static/js/modules/trace.js`

**Files:**
- Create: `web/static/js/modules/trace.js`

- [ ] **Step 1: Verify `web/static/js/modules/` exists**

```powershell
ls web/static/js/modules
```

If the directory doesn't exist yet (slice 02 should have created it), create it:

```powershell
New-Item -ItemType Directory -Force web/static/js/modules
```

- [ ] **Step 2: Write `trace.js`**

Create `web/static/js/modules/trace.js`:

```javascript
// web/static/js/modules/trace.js
//
// Trace panel renderer + polling lifecycle.
// Exported API:
//   debugUiEnabled()                                — boolean, combines template flag + ?debug=1
//   renderTrace(events, { debug, stageLabels })    — mutates the 6 cards in-place
//   startTracePolling(token, { debug, stageLabels })
//   stopTracePolling()
//
// Card row promotion (div -> button) happens lazily inside renderTrace
// the first time it sees a card with debug=true. Promotion is tracked
// via dataset.debugWired so we never wire twice.

const TRACE_POLL_INTERVAL_MS = 1000;

let tracePollTimer = null;
const expandedStages = new Set();

export function debugUiEnabled() {
  const fromGlobal = window.__debugUi === true;
  const fromTemplate = document.querySelector(".chat-shell")?.dataset.debugUi === "true";
  const fromUrl = new URLSearchParams(window.location.search).get("debug") === "1";
  return fromGlobal || fromTemplate || fromUrl;
}

function formatDuration(ms) {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function statusMeta(event) {
  switch (event.status) {
    case "completed": return formatDuration(event.duration_ms);
    case "running":   return "";           // spinner alone communicates state
    case "failed":    return "Lỗi";
    default:          return "";           // pending: empty (no "pending" noise)
  }
}

function statusSymbolId(status) {
  switch (status) {
    case "completed": return "icon-status-completed";
    case "running":   return "icon-status-running";
    case "failed":    return "icon-status-failed";
    default:          return "icon-status-pending";
  }
}

function setStatusIcon(card, status) {
  const useEl = card.querySelector(".trace-card__status .icon use");
  if (useEl) {
    useEl.setAttribute("href", `#${statusSymbolId(status)}`);
  }
}

function promoteRowToButton(card) {
  if (card.dataset.debugWired === "true") return;
  const row = card.querySelector(".trace-card__row");
  if (!row || row.tagName === "BUTTON") {
    card.dataset.debugWired = "true";
    return;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = row.className;
  button.setAttribute("aria-expanded", "false");
  while (row.firstChild) button.appendChild(row.firstChild);
  row.replaceWith(button);

  button.addEventListener("click", () => {
    const stage = card.dataset.stage;
    const body = card.querySelector(".trace-card__body");
    const expanded = expandedStages.has(stage);
    if (expanded) {
      expandedStages.delete(stage);
      body.hidden = true;
      button.setAttribute("aria-expanded", "false");
    } else {
      expandedStages.add(stage);
      body.hidden = false;
      button.setAttribute("aria-expanded", "true");
    }
  });

  card.dataset.debugWired = "true";
}

export function renderTrace(events, { debug, stageLabels } = {}) {
  const root = document.getElementById("trace-cards");
  if (!root) return;

  events.forEach((event) => {
    const card = root.querySelector(`[data-stage="${event.stage}"]`);
    if (!card) return;

    // Status class
    card.classList.remove(
      "trace-card--pending",
      "trace-card--running",
      "trace-card--completed",
      "trace-card--failed",
    );
    card.classList.add(`trace-card--${event.status}`);

    // Status icon swap
    setStatusIcon(card, event.status);

    // Meta text
    const metaEl = card.querySelector(".trace-card__meta");
    if (metaEl) metaEl.textContent = statusMeta(event);

    // Body content — debug-gated
    const body = card.querySelector(".trace-card__body");
    if (!body) return;

    if (debug) {
      promoteRowToButton(card);

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
      const row = card.querySelector(".trace-card__row");
      if (row && row.tagName === "BUTTON") {
        row.setAttribute("aria-expanded", String(isExpanded));
      }
    } else {
      // End-user mode: never inject JSON into the DOM
      body.textContent = "";
      body.hidden = true;
    }
  });
  // stageLabels is currently unused by renderTrace but reserved for
  // future i18n of meta strings ("Lỗi", duration suffix, etc.).
  void stageLabels;
}

async function fetchTrace(sessionToken) {
  const r = await fetch(`/api/sessions/${sessionToken}/trace`);
  if (!r.ok) throw new Error("trace fetch failed");
  return r.json();
}

export function stopTracePolling() {
  if (tracePollTimer) {
    window.clearTimeout(tracePollTimer);
    tracePollTimer = null;
  }
}

export function startTracePolling(sessionToken, opts = {}) {
  stopTracePolling();

  const tick = async () => {
    try {
      const payload = await fetchTrace(sessionToken);
      renderTrace(payload.events, opts);
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

- [ ] **Step 3: Manual smoke (module loads, no runtime errors)**

Reload `http://127.0.0.1:8000/?debug=1`. Open devtools console. There should be no `404` for `modules/trace.js` and no `SyntaxError`. (The module isn't wired into `chat.js` yet — that happens in Task 5. This step just verifies the file parses.)

- [ ] **Step 4: Commit**

```powershell
git add web/static/js/modules/trace.js
git commit -m @'
feat(ui): add modules/trace.js with debug-gated render + polling

Extracts trace rendering and polling out of chat.js into a dedicated
ES module. Exports renderTrace, startTracePolling, stopTracePolling,
and debugUiEnabled.

Key behaviors:
- End-user mode never injects JSON or error text into the DOM and
  keeps card rows as non-interactive `<div>`s.
- Debug mode lazily promotes `.trace-card__row` from `<div>` to
  `<button>` on first render (tracked via dataset.debugWired) and
  pretty-prints output_json on completed or error_text on failed.
- Status icons are swapped by mutating the `<use href>` attribute,
  pointing at one of four sprite symbol ids.
- Running cards show only the spinner (no "running…" text); failed
  cards show "Lỗi"; completed show formatted duration; pending shows
  empty meta.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 5: Refactor `chat.js` to import and use `trace.js`

**Files:**
- Modify: `web/static/js/chat.js`

- [ ] **Step 1: Remove the inline trace block + add imports**

In `web/static/js/chat.js`, **delete** the entire block from `const TRACE_POLL_INTERVAL_MS = 1000;` through the end of `function renderTraceCards(events) { … }` (roughly lines 3–81 in the current file). Specifically delete:

- `TRACE_POLL_INTERVAL_MS`
- `TRACE_STAGES`
- `tracePollTimer`
- `expandedStages` Set
- `debugUiEnabled()`
- `showTracePanel()`
- `fetchTrace()`
- `formatDuration()`
- `statusMeta()`
- `statusIcon()`
- `renderTraceCards()`

Also delete the standalone `stopTracePolling()` and `startTracePolling()` function declarations further down (currently lines ~86–111).

At the very top of `web/static/js/chat.js`, add the import (alongside whatever imports slice 02 / slice 03 already added):

```javascript
import {
  renderTrace,
  startTracePolling,
  stopTracePolling,
  debugUiEnabled,
} from "./modules/trace.js";
```

- [ ] **Step 2: Update the DOMContentLoaded handler**

In the `document.addEventListener("DOMContentLoaded", …)` body:

1. Remove the inline `document.querySelectorAll("#trace-cards .trace-card").forEach(...)` click-handler block — promotion + click-wiring now lives in `trace.js#promoteRowToButton`.

2. Replace the existing `if (debugUiEnabled()) { showTracePanel(); }` with:

```javascript
  const traceOpts = () => ({
    debug: debugUiEnabled(),
    stageLabels: window.__stageLabels || [],
  });

  if (debugUiEnabled()) {
    const panel = document.getElementById("trace-panel");
    if (panel) panel.hidden = false;
  }
```

3. Where the bootstrap block currently calls `startTracePolling(currentSessionToken)`, change to:

```javascript
    if (debugUiEnabled() && bootstrap.session && bootstrap.session.status === "running") {
      startTracePolling(currentSessionToken, traceOpts());
    }
```

4. In the form submit handler, where it currently calls `startTracePolling(currentSessionToken);`, change to:

```javascript
        startTracePolling(currentSessionToken, traceOpts());
```

5. In `schedulePolling`'s two terminal branches, replace the inline `fetchTrace(sessionToken).then((p) => renderTraceCards(p.events))` calls with a single final-render via `startTracePolling` *and* immediate stop — simplest is to delete the one-off fetch and let the polling loop's natural final tick handle it:

```javascript
    if (snapshot.session.status === "completed") {
      setStatus("Đã có kết quả tư vấn.", "success");
      stopPolling();
      stopTracePolling();
      return;
    }
    if (snapshot.session.status === "failed") {
      setStatus("Quá trình phân tích bị gián đoạn.", "error");
      stopPolling();
      stopTracePolling();
      return;
    }
```

> The trace poller terminates on its own when `run_status` is no longer `running`/`queued`, so the explicit `stopTracePolling()` here is belt-and-suspenders for the race where the snapshot reaches `completed` before the trace tick fires.

6. In the reset-button handler, the existing `stopTracePolling();` call still works unchanged (it's now the imported one).

- [ ] **Step 3: Manual smoke**

Reload `http://127.0.0.1:8000/?debug=1`. Open devtools console; there must be **no** `ReferenceError` for `fetchTrace`, `renderTraceCards`, `formatDuration`, etc. The page should render identically to before this task — the cards still show pending state and nothing breaks. Send a message that triggers a run and watch cards transition: pending → running → completed.

- [ ] **Step 4: Run the test suite**

```powershell
pytest tests/web/ -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```powershell
git add web/static/js/chat.js
git commit -m @'
refactor(ui): chat.js delegates trace logic to modules/trace.js

Removes ~80 lines of inline trace code from chat.js (TRACE_STAGES,
tracePollTimer, expandedStages, debugUiEnabled, showTracePanel,
fetchTrace, formatDuration, statusMeta, statusIcon, renderTraceCards,
startTracePolling, stopTracePolling, and the inline card click-handler
wiring) in favor of imports from ./modules/trace.js.

Trace polling now receives an opts bag `{ debug, stageLabels }` so the
module never reads globals directly outside of debugUiEnabled().
Terminal-state branches in schedulePolling stop trace polling
defensively; the poller already self-terminates when run_status flips
out of running/queued.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 6: Update `chat.css` — SVG icon sizing, status colors, connector line, button-as-row styles

**Files:**
- Modify: `web/static/css/chat.css`

- [ ] **Step 1: Replace the trace-panel CSS block**

In `web/static/css/chat.css`, **delete** the existing `/* ===== Trace panel ===== */` block in full (everything from that comment through the closing `@keyframes trace-spin { … }`). Replace with:

```css
/* ===== Trace panel ===== */

.trace-panel {
  background: var(--surface-2);
  border-left: 1px solid var(--surface-4);
  padding: var(--space-4) var(--space-5);
  min-width: 280px;
  max-width: 360px;
  overflow-y: auto;
}

.trace-panel h2 {
  margin: 0 0 var(--space-3);
  font-size: var(--text-md);
  color: var(--text-1);
}

.trace-cards {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.trace-card {
  position: relative;
  border: 1px solid var(--surface-4);
  border-radius: var(--radius-md);
  background: var(--surface-1);
  overflow: hidden;
  cursor: default;
}

/* Vertical connector line between cards (timeline feel).
   Sits centered under the icon column; only on non-last cards. */
.trace-card:not(:last-child)::after {
  content: "";
  position: absolute;
  left: calc(var(--space-3) + 9px); /* (row padding-left) + half of 18px icon */
  bottom: calc(-1 * var(--space-3));
  width: 1px;
  height: var(--space-3);
  background: var(--surface-4);
  pointer-events: none;
}

.trace-card__row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: transparent;
  border: 0;
  font: inherit;
  text-align: left;
  width: 100%;
  color: inherit;
}

/* Debug-mode promoted button row gets pointer + hover affordance */
.trace-card[data-debug-wired="true"] {
  cursor: pointer;
}
.trace-card[data-debug-wired="true"]:hover {
  background: var(--surface-3);
}

.trace-card__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  color: var(--text-2);
  flex: 0 0 auto;
}

.trace-card__name {
  flex: 1;
  font-weight: 600;
  color: var(--text-1);
}

.trace-card__status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
}

.trace-card__meta {
  font-size: var(--text-xs);
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  min-width: 32px;
  text-align: right;
}

.trace-card__body {
  margin: 0;
  padding: var(--space-3);
  background: var(--surface-2);
  border-top: 1px solid var(--surface-4);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-1);
}

/* SVG icon defaults — color follows currentColor on the surrounding span */
.icon {
  width: 100%;
  height: 100%;
  display: block;
}
.icon--stage  { width: 18px; height: 18px; }
.icon--status { width: 16px; height: 16px; }

/* Status variants drive icon + meta color via currentColor */
.trace-card--pending   .trace-card__status { color: var(--text-3); }
.trace-card--pending   .trace-card__meta   { color: var(--text-3); }

.trace-card--running   .trace-card__status {
  color: var(--warning);
  animation: trace-spin 1s linear infinite;
}
.trace-card--running   .trace-card__meta   { color: var(--warning); }

.trace-card--completed .trace-card__status { color: var(--positive); }
.trace-card--completed .trace-card__meta   { color: var(--positive); }

.trace-card--failed    .trace-card__status { color: var(--negative); }
.trace-card--failed    .trace-card__meta   { color: var(--negative); }

@keyframes trace-spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
```

- [ ] **Step 2: Manual visual check**

Reload `/?debug=1`. Verify:

1. Six cards render with stage icons on the left (user-circle, search, git-compare, lightbulb, shield-check, message-square) at 18×18.
2. A pending circle icon appears on the right of each card at 16×16, grey.
3. A faint 1px vertical line connects card N's icon column to card N+1.
4. Hover state appears only after debug-mode promotion has run (after the first trace render — trigger by sending any message).
5. After a run completes, completed cards show green check-circle + duration text.
6. After a run fails, failed cards show red x-circle + "Lỗi".
7. While a card is running, the refresh-cw icon spins via the existing `@keyframes trace-spin`.

- [ ] **Step 3: Commit**

```powershell
git add web/static/css/chat.css
git commit -m @'
feat(ui): trace card SVG-icon styles, connector line, debug-mode affordances

Replaces the textual-glyph status indicators (○ ⟳ ● ✕) with sized SVG
icons (18px stage, 16px status) colored via currentColor driven from
.trace-card--<status> modifier classes. Pending stays muted; running
animates with the existing trace-spin keyframe; completed turns
--positive (green); failed turns --negative (red).

Adds a 1px vertical connector line between consecutive cards via
::after pseudo on .trace-card:not(:last-child), positioned under the
icon column to give the timeline a continuous-thread feel.

Cards default to cursor: default; only cards with
data-debug-wired="true" (set by trace.js after promotion) gain
cursor: pointer + hover background. This keeps end-user mode from
implying interactivity that does nothing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 7: End-to-end smoke — full live run with debug enabled

**Files:** _none modified_

- [ ] **Step 1: Bring up the full stack**

```powershell
docker compose up -d --wait db
$env:GEMINI_API_KEY="<your key>"
$env:ADVISORY_DEBUG_UI="1"
uvicorn web.app:build_app --factory --reload --port 8000
```

- [ ] **Step 2: Smoke checklist**

Open `http://127.0.0.1:8000/?debug=1`. Walk through every item:

- [ ] All 6 cards render with Vietnamese labels (`Phân tích hồ sơ`, `Tra cứu chương trình`, `Đối chiếu nguồn dữ liệu`, `Suy luận khuyến nghị`, `Đối chiếu quy chế`, `Soạn lời giải thích`).
- [ ] Each card displays the correct stage SVG icon on the left (not text, not a broken-image glyph).
- [ ] A 1px connector line is visible between consecutive cards.
- [ ] All cards initially show a pending circle status icon (grey).
- [ ] Send "Em muốn học CNTT ở Hà Nội năm 2026, dự kiến được 27 điểm." to trigger a run.
- [ ] As the run progresses, the active stage's status icon flips to the running refresh-cw symbol and spins.
- [ ] Completed stages flip to green check-circle and show a duration like `1.2s` in the meta column.
- [ ] Cards become clickable (cursor: pointer + hover background) only after the first debug-mode render.
- [ ] Clicking a completed card expands the `<pre>` body and reveals pretty-printed `output_json`.
- [ ] Clicking again collapses it; the expanded set persists across re-renders during continued polling.
- [ ] Refresh the page mid-run: cards repaint correctly from the `/trace` endpoint without losing state.

- [ ] **Step 3: Negative — end-user mode**

```powershell
Remove-Item env:ADVISORY_DEBUG_UI
# Restart uvicorn
```

Reload `http://127.0.0.1:8000/` (no `?debug=1`). Confirm:

- [ ] Trace panel still renders with the same Vietnamese labels and SVG icons (the spec says the panel is visible once a run starts; verify after sending a message).
- [ ] Cards are **not** clickable (cursor stays `default`, no hover background).
- [ ] No `output_json` text appears anywhere in the DOM for completed cards (use devtools "Search all" for a string you know is in the latest `output_json` — should return zero hits inside `#trace-cards`).
- [ ] No `aria-expanded` attribute on rows.

- [ ] **Step 4: Run the full web test suite**

```powershell
pytest tests/web/ -v
```

Expected: all PASS.

- [ ] **Step 5: No commit**

This task is verification only; nothing to commit.

---

## Slice 04 Done When

- [ ] `web/routes/pages.py` defines `STAGE_LABELS` at module scope (6 entries with `id` / `label` / `icon`) and passes `stage_labels=STAGE_LABELS` to the chat template.
- [ ] `web/templates/chat.html` loops `{% for stage in stage_labels %}` to build the trace-card skeleton; each card row is a `<div class="trace-card__row">` (not a `<button>`) at render time.
- [ ] `web/templates/chat.html` contains an inline `<svg>` sprite at the top of `<body>` with ten `<symbol>` definitions (6 stage icons + 4 status icons), all using lucide MIT-licensed paths.
- [ ] `web/templates/chat.html` exposes `window.__stageLabels` (JSON) and `window.__debugUi` (boolean) via a small inline `<script>` block above `chat.js`.
- [ ] `web/static/js/modules/trace.js` exists and exports `renderTrace`, `startTracePolling`, `stopTracePolling`, `debugUiEnabled`.
- [ ] `web/static/js/chat.js` no longer contains `fetchTrace`, `renderTraceCards`, inline `startTracePolling`/`stopTracePolling`/`formatDuration`/`statusMeta`/`statusIcon`/`expandedStages`/`tracePollTimer`/`TRACE_POLL_INTERVAL_MS`/`TRACE_STAGES`/`debugUiEnabled`/`showTracePanel`; instead it imports from `./modules/trace.js`.
- [ ] Status icons render as SVG (no `○ ⟳ ● ✕` text glyphs remain in the trace-panel DOM); colors follow `--positive` / `--warning` / `--negative` / `--text-3` tokens.
- [ ] Cards display a 1px vertical connector line between siblings via `::after`.
- [ ] In end-user mode, `output_json` is never written into the DOM; cards are non-interactive (`cursor: default`).
- [ ] In debug mode, the first render promotes `.trace-card__row` from `<div>` to `<button>` (tracked via `dataset.debugWired`), clicks toggle the JSON body, expand state persists in the module-scoped `Set`.
- [ ] `tests/web/test_pages.py` asserts all 6 Vietnamese labels render, that `window.__stageLabels` script is present, and that the SVG sprite contains `<symbol id="icon-user-circle"` and `<symbol id="icon-status-pending"`.
- [ ] `pytest tests/web/ -v` passes; full live run smoke (Task 7 Step 2) passes both with and without `?debug=1`.
- [ ] Each of Tasks 1–6 produced one commit using the HEREDOC + `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.
