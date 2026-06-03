# Slice 02 — Shell & Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the chat page body into a 3-column CSS Grid shell (profile / chat / trace) with collapse-able side panels, a sticky app header, persisted collapse state, and a mobile drawer for the side panels — using only design tokens from slice 01, without touching message bubble markdown or stage-label i18n (those land in slices 03/04).

**Architecture:** `chat.html` becomes `.app-shell > .app-header + main.grid-3col`, where `main` is a CSS Grid with three children — `<aside id="profile-panel">`, `<section id="chat-panel">`, `<aside id="trace-panel">`. Column widths are CSS custom properties (`--col-left`, `--col-right`) toggled by `.left-collapsed` / `.right-collapsed` modifier classes on `.app-shell`. A new ES module `web/static/js/modules/layout.js` wires collapse chevron buttons, persists state in `localStorage.layout`, and at `< 900px` swaps the side panels into fixed-position drawers opened by header buttons. Existing IDs (`chat-transcript`, `chat-form`, `chat-input`, `send-button`, `chat-status`, `profile-summary`, `recommendation-panel`, `trace-panel`, `trace-cards`, `reset-session`) are preserved so the existing `chat.js` orchestrator and trace-card logic keep working until slice 03 swaps them.

**Tech Stack:** Jinja2, vanilla JS ES modules, CSS custom properties / Grid, FastAPI TestClient for HTML structure assertions.

---

### Task 1: Rewrite chat.html body to 3-column shell (TDD on structure)

**Files:**
- Modify: `tests/web/test_chat_page.py`
- Modify: `web/templates/chat.html`

- [ ] **Step 1: Write the failing structural test**

Replace the contents of `tests/web/test_chat_page.py` with:

```python
from fastapi.testclient import TestClient

from web.app import build_app


def test_chat_page_renders_status_reset_and_results_regions():
    client = TestClient(build_app())

    response = client.get("/")

    assert response.status_code == 200
    assert 'id="chat-status"' in response.text
    assert 'id="reset-session"' in response.text
    assert 'id="recommendation-panel"' in response.text
    assert 'id="send-button"' in response.text


def test_chat_page_renders_three_column_shell():
    client = TestClient(build_app())

    response = client.get("/")
    body = response.text

    assert response.status_code == 200
    assert 'class="app-shell"' in body
    assert 'class="app-header"' in body
    assert 'id="profile-panel"' in body
    assert 'id="chat-panel"' in body
    assert 'id="trace-panel"' in body


def test_chat_page_renders_collapse_and_drawer_buttons():
    client = TestClient(build_app())

    response = client.get("/")
    body = response.text

    assert response.status_code == 200
    assert 'id="collapse-left"' in body
    assert 'id="collapse-right"' in body
    assert 'id="open-left-drawer"' in body
    assert 'id="open-right-drawer"' in body


def test_chat_page_preserves_legacy_ids_for_existing_js():
    client = TestClient(build_app())

    response = client.get("/")
    body = response.text

    assert response.status_code == 200
    for legacy in ("chat-transcript", "chat-form", "chat-input", "profile-summary", "trace-cards"):
        assert f'id="{legacy}"' in body
```

- [ ] **Step 2: Run to confirm failure**

```powershell
pytest tests/web/test_chat_page.py -v
```
Expected: the first test still passes; the three new tests FAIL (panels and shell classes don't exist yet).

- [ ] **Step 3: Rewrite `web/templates/chat.html` body**

Replace the entire file with:

```html
{% extends "base.html" %}
{% block body %}
<div class="app-shell" data-debug-ui="{{ 'true' if debug_ui_enabled else 'false' }}">
  <header class="app-header">
    <div class="app-header__brand">
      <span class="app-header__logo" aria-hidden="true">A</span>
      <h1 class="app-header__title">Tư vấn tuyển sinh AI</h1>
    </div>
    <div class="app-header__actions">
      <button
        id="open-left-drawer"
        type="button"
        class="icon-button app-header__drawer-trigger"
        aria-label="Mở hồ sơ"
        aria-controls="profile-panel"
      >
        <span aria-hidden="true">☰</span>
      </button>
      <button
        id="open-right-drawer"
        type="button"
        class="icon-button app-header__drawer-trigger"
        aria-label="Mở phân tích AI"
        aria-controls="trace-panel"
      >
        <span aria-hidden="true">⋮</span>
      </button>
      <button
        id="theme-toggle"
        type="button"
        class="icon-button"
        aria-label="Đổi giao diện sáng/tối"
      >
        <span aria-hidden="true">🌙</span>
      </button>
      <button id="reset-session" type="button" class="secondary-button">Bắt đầu lại</button>
    </div>
  </header>

  <main class="grid-3col">
    <aside class="panel panel--side panel--left" id="profile-panel" aria-label="Hồ sơ học sinh">
      <div class="panel__header">
        <h2 class="panel__title">Hồ sơ</h2>
        <button
          id="collapse-left"
          type="button"
          class="icon-button panel__collapse"
          aria-label="Thu gọn cột hồ sơ"
          aria-controls="profile-panel"
        >
          <span aria-hidden="true">◀</span>
        </button>
      </div>
      <div class="panel__body">
        <section class="card" id="profile-summary-card">
          <h3 class="card__title">Hồ sơ tạm thời</h3>
          <div class="card__body" id="profile-summary"></div>
        </section>
        <section class="card" id="recommendation-card">
          <h3 class="card__title">Khuyến nghị mới nhất</h3>
          <div class="card__body" id="recommendation-panel"></div>
        </section>
      </div>
    </aside>

    <section class="panel panel--center" id="chat-panel" aria-label="Hội thoại">
      <div id="chat-status" class="chat-status" aria-live="polite"></div>
      <div id="chat-transcript" class="chat-transcript" aria-live="polite"></div>
      <form id="chat-form" class="composer">
        <label for="chat-input" class="sr-only">Nội dung tin nhắn</label>
        <textarea
          id="chat-input"
          class="composer__input"
          name="content"
          rows="3"
          placeholder="Ví dụ: Em muốn học CNTT ở Hà Nội năm 2026, dự kiến được 27 điểm."
        ></textarea>
        <div class="composer__actions">
          <span class="composer__hint">Ctrl+Enter để gửi</span>
          <button id="send-button" type="submit" class="primary-button">Gửi</button>
        </div>
      </form>
    </section>

    <aside class="panel panel--side panel--right" id="trace-panel" aria-label="Phân tích của AI">
      <div class="panel__header">
        <button
          id="collapse-right"
          type="button"
          class="icon-button panel__collapse"
          aria-label="Thu gọn cột phân tích"
          aria-controls="trace-panel"
        >
          <span aria-hidden="true">▶</span>
        </button>
        <h2 class="panel__title">Phân tích của AI</h2>
      </div>
      <div class="panel__body">
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
      </div>
    </aside>
  </main>

  <div id="drawer-backdrop" class="drawer-backdrop" hidden></div>
</div>
{% endblock %}
```

Notes:
- `data-debug-ui` migrated from the old `<main>` to the new `<div class="app-shell">` so `chat.js`'s `debugUiEnabled()` lookup keeps working (it queries `.chat-shell` today — slice 04 will move it into `trace.js` and key it off `window.__debugUi`; for now we keep BOTH classes on the wrapper so the existing inline implementation keeps finding the attribute). To avoid that risk, add the legacy class too:

  Change the opening `<div>` to:
  ```html
  <div class="app-shell chat-shell" data-debug-ui="{{ 'true' if debug_ui_enabled else 'false' }}">
  ```
- The `hidden` attribute is intentionally **not** on `#trace-panel` anymore: the panel is part of the grid; visibility for non-debug users is owned by a future slice. Existing JS that does `panel.hidden = false` becomes a no-op (idempotent).

- [ ] **Step 4: Run the tests to confirm green**

```powershell
pytest tests/web/test_chat_page.py -v
```
Expected: all four tests PASS. Also re-run the full web test suite to confirm we did not regress slice 04 expectations:
```powershell
pytest tests/web -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add web/templates/chat.html tests/web/test_chat_page.py
git commit -m @'
feat(web): rewrite chat page as 3-column app shell

Replaces the legacy 2-column chat-shell with an app-shell wrapper
containing a sticky app-header and a grid-3col main with profile,
chat, and trace panels. Keeps all legacy IDs so existing chat.js
orchestrator continues to work until slice 03 takes over the
message rendering layer.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 2: Rewrite chat.css core layout (shell, header, grid, panel base)

**Files:**
- Modify: `web/static/css/chat.css`

- [ ] **Step 1: Replace the file's top half with token-driven core layout**

Replace the entire contents of `web/static/css/chat.css` with the block below. (Existing trace card styles are restyled in Task 3 — for now the file shrinks intentionally; the cards will look unstyled until Task 3 runs.)

```css
/* ============================================================
   chat.css — slice 02 core (shell + header + grid + panel base)
   All values consume tokens from tokens.css.
   ============================================================ */

*,
*::before,
*::after {
  box-sizing: border-box;
}

html,
body {
  margin: 0;
  height: 100%;
}

body {
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: var(--leading-base);
  color: var(--text-1);
  background: var(--surface-1);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

/* ----- App shell ----- */

.app-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--surface-1);
}

/* ----- Header ----- */

.app-header {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  height: var(--header-h);
  padding: 0 var(--space-4);
  background: var(--surface-2);
  border-bottom: 1px solid var(--surface-4);
}

.app-header__brand {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.app-header__logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-md);
  background: var(--accent-1);
  color: var(--accent-1-contrast);
  font-weight: 700;
  font-size: var(--text-sm);
}

.app-header__title {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-1);
}

.app-header__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* ----- Generic buttons ----- */

.icon-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  color: var(--text-2);
  cursor: pointer;
  font-size: var(--text-md);
  line-height: 1;
  transition:
    background var(--transition-fast),
    color var(--transition-fast),
    border-color var(--transition-fast);
}

.icon-button:hover {
  background: var(--surface-3);
  color: var(--text-1);
}

.icon-button:focus-visible {
  outline: 2px solid var(--accent-1);
  outline-offset: 2px;
}

.primary-button {
  padding: var(--space-2) var(--space-4);
  background: var(--accent-1);
  color: var(--accent-1-contrast);
  border: 0;
  border-radius: var(--radius-md);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.primary-button:hover {
  background: var(--accent-1-hover);
}

.primary-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.secondary-button {
  padding: var(--space-2) var(--space-3);
  background: var(--surface-2);
  color: var(--text-1);
  border: 1px solid var(--surface-4);
  border-radius: var(--radius-md);
  font: inherit;
  cursor: pointer;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast);
}

.secondary-button:hover {
  background: var(--surface-3);
}

/* ----- Main grid ----- */

.grid-3col {
  display: grid;
  grid-template-columns: var(--col-left) minmax(0, 1fr) var(--col-right);
  flex: 1 1 auto;
  min-height: 0;
}

/* ----- Panel base ----- */

.panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--surface-1);
  overflow: hidden;
}

.panel--side {
  background: var(--surface-2);
}

.panel--left {
  border-right: 1px solid var(--surface-4);
}

.panel--right {
  border-left: 1px solid var(--surface-4);
}

.panel--center {
  background: var(--surface-1);
}

.panel__header {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: inherit;
  border-bottom: 1px solid var(--surface-4);
}

.panel__title {
  margin: 0;
  font-size: var(--text-sm);
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--text-2);
  text-transform: uppercase;
}

.panel__body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
```

- [ ] **Step 2: Manual visual check**

Start the dev server (use whichever DB or stub setup the project already documents — for a layout-only pass, an empty session is fine):

```powershell
$env:ADVISORY_DEBUG_UI="1"
uvicorn web.app:build_app --factory --reload --port 8000
```

Open `http://127.0.0.1:8000/?debug=1`. Verify:
- Sticky 56px header bar appears at top with `Tư vấn tuyển sinh AI` title and three header buttons (drawer-left, drawer-right, theme, reset).
- Below the header, three columns line up: profile (left, 280px), chat (center, flex), trace (right, 320px).
- Each side panel has its own header with the panel title and a chevron-style collapse button.
- The composer textarea and Gửi button still render inside the center column (unstyled bubbles in the transcript are expected — slice 03 reskins them).

- [ ] **Step 3: Commit**

```powershell
git add web/static/css/chat.css
git commit -m @'
feat(ui): token-driven app shell, header, and 3-col grid layout

Rewrites chat.css base to consume tokens.css custom properties for
all colors, spacing, and typography. Introduces .app-shell column
flex, sticky .app-header, .grid-3col CSS Grid with --col-left and
--col-right custom properties, and .panel base with sticky header
plus scrollable body.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 3: Re-skin profile cards, chat panel, composer, and trace cards using tokens

**Files:**
- Modify: `web/static/css/chat.css`

- [ ] **Step 1: Append component styles**

Append the following block to `web/static/css/chat.css`:

```css
/* ----- Profile cards ----- */

.card {
  background: var(--surface-1);
  border: 1px solid var(--surface-4);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
}

.card__title {
  margin: 0;
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-1);
  border-bottom: 1px solid var(--surface-4);
}

.card__body {
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-sm);
  color: var(--text-2);
  line-height: var(--leading-base);
  white-space: pre-wrap;
}

.card__body p {
  margin: 0 0 var(--space-2);
}

.card__body p:last-child {
  margin-bottom: 0;
}

/* ----- Chat panel ----- */

.chat-status {
  min-height: 20px;
  padding: 0 var(--space-4);
  font-size: var(--text-sm);
  color: var(--text-2);
}

.chat-status[data-tone="pending"] { color: var(--warning); }
.chat-status[data-tone="success"] { color: var(--positive); }
.chat-status[data-tone="error"]   { color: var(--negative); }

.chat-transcript {
  flex: 1 1 auto;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  min-height: 0;
}

/* Legacy message bubble styles — slice 03 will replace. Kept functional. */
.message {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  line-height: var(--leading-base);
  white-space: pre-wrap;
  max-width: var(--bubble-max);
}

.message--assistant {
  background: var(--assistant-bg);
  align-self: flex-start;
  border-bottom-left-radius: var(--radius-sm);
}

.message--user {
  background: var(--user-bubble);
  align-self: flex-end;
  border-bottom-right-radius: var(--radius-sm);
}

/* ----- Composer ----- */

.composer {
  position: sticky;
  bottom: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4) var(--space-4);
  background: var(--surface-1);
  border-top: 1px solid var(--surface-4);
}

.composer__input {
  width: 100%;
  min-height: 64px;
  padding: var(--space-3);
  font-family: var(--font-sans);
  font-size: var(--text-md);
  line-height: var(--leading-base);
  color: var(--text-1);
  background: var(--surface-2);
  border: 1px solid var(--surface-4);
  border-radius: var(--radius-md);
  resize: vertical;
}

.composer__input:focus-visible {
  outline: 2px solid var(--accent-1);
  outline-offset: 0;
  border-color: transparent;
}

.composer__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.composer__hint {
  font-size: var(--text-xs);
  color: var(--text-3);
}

/* ----- Trace cards (re-skinned with tokens) ----- */

.trace-cards {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.trace-card {
  border: 1px solid var(--surface-4);
  border-radius: var(--radius-md);
  background: var(--surface-1);
  overflow: hidden;
}

.trace-card__header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: transparent;
  border: 0;
  cursor: pointer;
  font: inherit;
  text-align: left;
  color: var(--text-1);
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
  font-size: var(--text-sm);
}

.trace-card__meta {
  font-size: var(--text-xs);
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
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
  color: var(--text-2);
}

.trace-card--pending   .trace-card__icon { color: var(--text-3); }
.trace-card--pending   .trace-card__meta { color: var(--text-3); }

.trace-card--running   .trace-card__icon {
  color: var(--warning);
  display: inline-block;
  animation: trace-spin 1s linear infinite;
}

.trace-card--completed .trace-card__icon { color: var(--positive); }
.trace-card--completed .trace-card__meta { color: var(--positive); }

.trace-card--failed    .trace-card__icon { color: var(--negative); }
.trace-card--failed    .trace-card__meta { color: var(--negative); }

@keyframes trace-spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
```

- [ ] **Step 2: Manual visual check**

Reload `http://127.0.0.1:8000/?debug=1`. Verify:
- Profile panel shows two cards (`Hồ sơ tạm thời`, `Khuyến nghị mới nhất`) with subtle border and shadow.
- Composer sits at the bottom of the chat panel with the `Ctrl+Enter để gửi` hint and the Gửi button on the right.
- Trace cards render in the right column with token colors; sending a message and watching a run still produces the spinner / green check transitions.

- [ ] **Step 3: Commit**

```powershell
git add web/static/css/chat.css
git commit -m @'
feat(ui): re-skin profile cards, composer, and trace cards via tokens

Adds token-driven styles for .card / .card__title / .card__body,
the sticky .composer with textarea + Gửi action row, the legacy
.message bubbles (preserved for slice 03 swap), and re-skins the
trace cards using --positive / --warning / --negative tokens so
dark theme automatically inherits the right palette.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 4: Add collapse modifier classes + chevron button styles

**Files:**
- Modify: `web/static/css/chat.css`

- [ ] **Step 1: Append collapse styles**

Append to `web/static/css/chat.css`:

```css
/* ----- Collapse modifiers ----- */

.app-shell.left-collapsed  { --col-left: 32px;  }
.app-shell.right-collapsed { --col-right: 32px; }

.app-shell.left-collapsed  #profile-panel .panel__body,
.app-shell.left-collapsed  #profile-panel .panel__title,
.app-shell.right-collapsed #trace-panel  .panel__body,
.app-shell.right-collapsed #trace-panel  .panel__title {
  display: none;
}

.app-shell.left-collapsed  #profile-panel .panel__header,
.app-shell.right-collapsed #trace-panel  .panel__header {
  padding: var(--space-2) 0;
  justify-content: center;
  border-bottom: 0;
}

.panel__collapse {
  flex: 0 0 auto;
}

/* Rotate the chevron when collapsed so the same glyph points outward. */
.app-shell.left-collapsed  #collapse-left  span { transform: rotate(180deg); display: inline-block; }
.app-shell.right-collapsed #collapse-right span { transform: rotate(180deg); display: inline-block; }
```

- [ ] **Step 2: Manual visual check**

In DevTools console, add the class manually first to verify the styling without JS:
```javascript
document.querySelector('.app-shell').classList.add('left-collapsed');
document.querySelector('.app-shell').classList.add('right-collapsed');
```
Expected:
- Both side columns shrink to a 32px gutter.
- Only the chevron buttons remain visible; their glyphs point outward.
- The center chat panel widens accordingly.

Remove the classes to confirm the panels re-expand:
```javascript
document.querySelector('.app-shell').classList.remove('left-collapsed', 'right-collapsed');
```

- [ ] **Step 3: Commit**

```powershell
git add web/static/css/chat.css
git commit -m @'
feat(ui): collapsed-column modifier classes + chevron rotation

Adds .app-shell.left-collapsed / .right-collapsed modifiers that
override --col-left / --col-right to a 32px gutter and hide the
panel body / title, leaving only the chevron button. Rotates the
chevron glyph 180deg so the same character points outward when
collapsed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 5: Create layout.js module with collapse handles + localStorage persistence

**Files:**
- Create: `web/static/js/modules/layout.js`

- [ ] **Step 1: Author the module**

Create `web/static/js/modules/layout.js` with the following contents:

```javascript
// web/static/js/modules/layout.js
// Layout helpers: collapse-able side panels (persisted) + mobile drawers.

const LAYOUT_STORAGE_KEY = "layout";
const MOBILE_QUERY = "(max-width: 899px)";

function readLayoutState() {
  try {
    const raw = window.localStorage.getItem(LAYOUT_STORAGE_KEY);
    if (!raw) return { left: false, right: false };
    const parsed = JSON.parse(raw);
    return {
      left: Boolean(parsed.left),
      right: Boolean(parsed.right),
    };
  } catch {
    return { left: false, right: false };
  }
}

function writeLayoutState(state) {
  try {
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* storage unavailable; skip persistence */
  }
}

function applyCollapsed(shell, state) {
  shell.classList.toggle("left-collapsed", state.left);
  shell.classList.toggle("right-collapsed", state.right);
  const leftPanel = document.getElementById("profile-panel");
  const rightPanel = document.getElementById("trace-panel");
  if (leftPanel) leftPanel.setAttribute("aria-hidden", String(state.left));
  if (rightPanel) rightPanel.setAttribute("aria-hidden", String(state.right));
}

function wireCollapseButton(shell, state, side) {
  const buttonId = side === "left" ? "collapse-left" : "collapse-right";
  const button = document.getElementById(buttonId);
  if (!button) return;
  button.addEventListener("click", () => {
    state[side] = !state[side];
    applyCollapsed(shell, state);
    writeLayoutState(state);
  });
}

function closeDrawerInternal() {
  document.body.classList.remove("drawer-open--left", "drawer-open--right");
  const backdrop = document.getElementById("drawer-backdrop");
  if (backdrop) backdrop.hidden = true;
}

function openDrawerInternal(side) {
  const cls = side === "left" ? "drawer-open--left" : "drawer-open--right";
  document.body.classList.remove("drawer-open--left", "drawer-open--right");
  document.body.classList.add(cls);
  const backdrop = document.getElementById("drawer-backdrop");
  if (backdrop) backdrop.hidden = false;
}

function wireDrawerButton(side) {
  const buttonId = side === "left" ? "open-left-drawer" : "open-right-drawer";
  const button = document.getElementById(buttonId);
  if (!button) return;
  button.addEventListener("click", () => openDrawerInternal(side));
}

function wireDrawerDismiss() {
  const backdrop = document.getElementById("drawer-backdrop");
  if (backdrop) {
    backdrop.addEventListener("click", closeDrawerInternal);
  }
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeDrawerInternal();
  });
}

function syncDrawerForViewport(mql) {
  // When transitioning out of mobile, ensure no stale drawer state lingers.
  if (!mql.matches) closeDrawerInternal();
}

export function openDrawer(side) {
  openDrawerInternal(side === "right" ? "right" : "left");
}

export function closeDrawer() {
  closeDrawerInternal();
}

export function initCollapseHandles() {
  const shell = document.querySelector(".app-shell");
  if (!shell) return;

  const state = readLayoutState();
  applyCollapsed(shell, state);

  wireCollapseButton(shell, state, "left");
  wireCollapseButton(shell, state, "right");
  wireDrawerButton("left");
  wireDrawerButton("right");
  wireDrawerDismiss();

  const mql = window.matchMedia(MOBILE_QUERY);
  syncDrawerForViewport(mql);
  if (typeof mql.addEventListener === "function") {
    mql.addEventListener("change", syncDrawerForViewport);
  } else if (typeof mql.addListener === "function") {
    // Safari < 14 fallback
    mql.addListener(syncDrawerForViewport);
  }
}
```

- [ ] **Step 2: Verify the file is loadable**

Quick syntax sanity check (no JS test runner, but Node can parse modules):

```powershell
node --check web/static/js/modules/layout.js
```
Expected: exit 0, no output. If `node` is unavailable, skip — Task 6 manual smoke will surface any syntax error.

- [ ] **Step 3: Commit**

```powershell
git add web/static/js/modules/layout.js
git commit -m @'
feat(ui): layout module with collapse persistence + drawer helpers

Adds web/static/js/modules/layout.js exposing initCollapseHandles,
openDrawer, and closeDrawer. Wires the left/right collapse chevron
buttons to toggle .left-collapsed / .right-collapsed on .app-shell
and persists state in localStorage.layout. Wires the mobile drawer
trigger buttons (header chevrons) and dismissal via backdrop click
or Escape key, and clears stale drawer classes on viewport change.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 6: Wire chat.js to load layout module on DOMContentLoaded

**Files:**
- Modify: `web/static/js/chat.js`

**Pre-condition reminder:** Slice 01 already converted the `<script>` tag for `chat.js` in `base.html` to `type="module"`, so ES `import` statements are valid here.

- [ ] **Step 1: Add the import at the top of `chat.js`**

At the very top of `web/static/js/chat.js`, before `const SESSION_KEY = ...`, add:

```javascript
import { initCollapseHandles } from "./modules/layout.js";
```

- [ ] **Step 2: Call `initCollapseHandles()` inside DOMContentLoaded**

In `web/static/js/chat.js`, find the `document.addEventListener("DOMContentLoaded", async () => {` line. Immediately after the opening brace and the existing `const form = ...` / `const input = ...` / `const resetButton = ...` lines, insert:

```javascript
  initCollapseHandles();
```

(Place it before the `if (debugUiEnabled()) { showTracePanel(); }` block so collapse/restore happens first.)

- [ ] **Step 3: Manual smoke check**

Reload `http://127.0.0.1:8000/?debug=1` and:
1. Click the left chevron — profile panel collapses to a 32px gutter; the chevron now points right.
2. Click the right chevron — trace panel collapses; chat panel widens fully.
3. Reload the page — both panels remain collapsed (localStorage persisted).
4. Click chevrons again to re-expand — reload — both panels remain expanded.
5. Open DevTools → Application → Local Storage → confirm a `layout` key with `{"left":false,"right":false}` (or the relevant boolean combo).

- [ ] **Step 4: Confirm no regressions in existing tests**

```powershell
pytest tests/web -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add web/static/js/chat.js
git commit -m @'
feat(ui): wire layout module into chat.js bootstrap

Imports initCollapseHandles from the new layout module and invokes
it at the top of the DOMContentLoaded handler so collapse state is
restored from localStorage before any other UI work runs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 7: Responsive breakpoints — auto-collapse at 1100px, drawers at 900px

**Files:**
- Modify: `web/static/css/chat.css`

- [ ] **Step 1: Append media queries**

Append to `web/static/css/chat.css`:

```css
/* ============================================================
   Responsive layout
   ============================================================ */

/* Default desktop: drawer-trigger buttons hidden. */
.app-header__drawer-trigger {
  display: none;
}

/* Tablet — collapse trace panel by default. */
@media (max-width: 1099px) {
  .app-shell:not(.right-collapsed) {
    --col-right: 32px;
  }
  .app-shell:not(.right-collapsed) #trace-panel .panel__body,
  .app-shell:not(.right-collapsed) #trace-panel .panel__title {
    display: none;
  }
  .app-shell:not(.right-collapsed) #trace-panel .panel__header {
    padding: var(--space-2) 0;
    justify-content: center;
    border-bottom: 0;
  }
}

/* Mobile — both side panels become drawers. */
@media (max-width: 899px) {
  .grid-3col {
    grid-template-columns: minmax(0, 1fr);
  }

  .panel--side {
    display: none;
  }

  .app-header__drawer-trigger {
    display: inline-flex;
  }

  /* Drawer surfaces (shown when body has .drawer-open--*). */
  body.drawer-open--left  #profile-panel,
  body.drawer-open--right #trace-panel {
    display: flex;
    position: fixed;
    top: var(--header-h);
    bottom: 0;
    width: min(85vw, 320px);
    z-index: 30;
    box-shadow: var(--shadow-md);
    background: var(--surface-2);
    transition: transform var(--transition-base);
  }

  body.drawer-open--left  #profile-panel { left: 0;  border-right: 1px solid var(--surface-4); }
  body.drawer-open--right #trace-panel  { right: 0; border-left:  1px solid var(--surface-4); }

  .drawer-backdrop {
    position: fixed;
    inset: var(--header-h) 0 0 0;
    z-index: 25;
    background: rgba(0, 0, 0, 0.4);
  }
}
```

- [ ] **Step 2: Manual responsive check**

In DevTools, toggle the device toolbar and resize:
- **1280px**: full 3-column layout, drawer-trigger buttons hidden in header.
- **1000px** (tablet): trace panel auto-collapses to gutter; click its chevron → trace panel re-expands (overrides the auto-collapse via `:not(.right-collapsed)` selector inversion — actually verify this: clicking the chevron toggles `.right-collapsed`, which short-circuits the media-query rule).
- **800px** (mobile): both side panels disappear from the flow; header shows two drawer-trigger buttons (`☰` left, `⋮` right) plus the theme + reset buttons; chat fills the viewport.

(Drawer open/close interaction itself lands in Task 8.)

- [ ] **Step 3: Commit**

```powershell
git add web/static/css/chat.css
git commit -m @'
feat(ui): responsive breakpoints for tablet collapse + mobile drawers

At <=1099px the trace panel auto-collapses to a 32px gutter unless
the user has explicitly toggled .right-collapsed off. At <=899px
the side panels leave the grid entirely and the header reveals
two drawer-trigger buttons; when the body carries a drawer-open
modifier, the matching panel re-renders as a fixed overlay with a
backdrop.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 8: Drawer JS interaction verified end-to-end

**Files:**
- (Verification only — layout.js already exposes the drawer plumbing from Task 5.)

- [ ] **Step 1: Manual drawer smoke**

In Chrome DevTools, set the viewport to 800px wide:
1. Click the `☰` (left drawer) button in the header → profile panel slides in from the left as a fixed overlay; backdrop appears.
2. Click the backdrop → drawer closes; backdrop disappears.
3. Open the left drawer again, press `Esc` → drawer closes.
4. Click the `⋮` (right drawer) button → trace panel slides in from the right.
5. Open the right drawer, then resize the viewport back to 1200px → drawer classes clear; layout returns to the full 3-column grid without a lingering backdrop.

- [ ] **Step 2: Quick a11y check**

While each drawer is open, confirm in DevTools:
- The relevant header trigger still has `aria-controls` pointing at the panel ID.
- The hidden side panel of the *other* side stays `display: none` (no double-overlay).
- Tabbing from the drawer trigger lands somewhere inside the now-visible panel (focus management polish lands in slice 05; for slice 02 we only confirm nothing is keyboard-trapped).

- [ ] **Step 3: Run all web tests again**

```powershell
pytest tests/web -v
```
Expected: PASS.

- [ ] **Step 4: Commit (if no changes were needed)**

If Task 5 already covers everything (most likely path), skip the commit. If any small fix landed in `layout.js` during the smoke (e.g., a typo), commit it as:

```powershell
git add web/static/js/modules/layout.js
git commit -m @'
fix(ui): drawer interaction polish from manual smoke

Adjustments uncovered while exercising the mobile drawer flow at
800px viewport (backdrop dismiss, Escape handling, viewport-change
cleanup).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 9: Final visual smoke + cross-theme verification

**Files:**
- (No file edits — sanity sweep before declaring slice complete.)

- [ ] **Step 1: Desktop sweep — light theme**

With `ADVISORY_DEBUG_UI=1` and the page at `?debug=1`:
- Header bar sticky and 56px.
- Profile / chat / trace columns render at 280 / fluid / 320.
- Chevrons collapse each side independently; state persists across reload.
- Composer textarea + Gửi button visible at the bottom of the chat panel.
- Trace cards still render with pending / running / completed / failed colors.

- [ ] **Step 2: Desktop sweep — dark theme**

Click the `🌙` header toggle (wired by slice 01's theme module). Verify:
- All surfaces flip to dark via tokens; no hardcoded light backgrounds linger.
- Borders, button hover states, card shadows still readable.
- Trace card icon colors (`--positive`, `--warning`, `--negative`) remain legible.

- [ ] **Step 3: Tablet sweep (1000px)**

- Trace panel auto-collapses; chat widens to fill.
- Click right chevron to expand it manually → works.

- [ ] **Step 4: Mobile sweep (800px)**

- Side panels gone from the flow; header gains two drawer triggers.
- Each drawer opens, backdrop dismisses, Escape dismisses.

- [ ] **Step 5: Regression tests**

```powershell
pytest tests/web -v
pytest -m "not integration"
```
Expected: PASS on both.

- [ ] **Step 6: (Optional) sanity-commit a no-op marker**

No commit needed if no files changed. Otherwise group with Task 8.

---

## Slice 02 Done When

- [ ] `web/templates/chat.html` body is a `.app-shell` wrapper containing `.app-header` + `main.grid-3col` with `#profile-panel`, `#chat-panel`, `#trace-panel` as direct grid children.
- [ ] `web/static/css/chat.css` is rewritten to consume tokens for all colors, spacing, radius, and typography — no hardcoded light-mode hex colors remain in layout-critical selectors.
- [ ] `.app-shell.left-collapsed` and `.app-shell.right-collapsed` shrink the corresponding column to 32px and hide its body, leaving only a chevron button.
- [ ] Collapse state for both columns persists across reloads via `localStorage.layout`.
- [ ] At `max-width: 1099px`, the trace panel auto-collapses unless the user has explicitly expanded it.
- [ ] At `max-width: 899px`, both side panels leave the flow and are accessible via header drawer-trigger buttons; backdrop click and Escape dismiss the drawer.
- [ ] `web/static/js/modules/layout.js` exists and exports `initCollapseHandles`, `openDrawer`, `closeDrawer`.
- [ ] `web/static/js/chat.js` imports and calls `initCollapseHandles()` on DOMContentLoaded.
- [ ] Legacy IDs (`chat-transcript`, `chat-form`, `chat-input`, `send-button`, `chat-status`, `reset-session`, `profile-summary`, `recommendation-panel`, `trace-panel`, `trace-cards`) are preserved so the existing orchestrator and slice-04 trace-card logic keep functioning.
- [ ] `tests/web/test_chat_page.py` covers the three new structural assertions (3 panels present, `.app-shell` + `.app-header` classes, both collapse buttons + both drawer-trigger buttons) and all four tests pass.
- [ ] `pytest tests/web -v` and `pytest -m "not integration"` both pass.
- [ ] Manual smoke at 1280 / 1000 / 800 px viewports + light/dark themes shows the layout behaves as described.
