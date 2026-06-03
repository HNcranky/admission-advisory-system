# Slice 01 — Tokens & Theme Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay down the design-system foundation (oklch tokens, FOUC-safe theme init, top header bar with a working theme-toggle button) without restyling the existing 2-column chat body — later slices own the full 3-column rewrite.

**Architecture:** A new `tokens.css` defines all light/dark CSS custom properties keyed off `<html data-theme="...">`. The server reads `ADVISORY_THEME_DEFAULT` env (default `"light"`) and exposes it to the template as `theme_default`, stored on `<html data-theme-default="...">`. An inline `<script>` in `<head>` (FOUC guard) sets `data-theme` from `localStorage` first, then the `data-theme-default` attribute, finally the `prefers-color-scheme` media query. A new ES module `web/static/js/modules/theme.js` exports `initTheme()` and `toggleTheme()`; `chat.js` becomes `type="module"` and calls `initTheme()` on DOM ready. The chat template gains a sticky 56px header bar that contains the theme-toggle button — the rest of the body STAYS as today's 2-column layout (Slice 02 owns the full grid rewrite).

**Tech Stack:** FastAPI + Jinja2, vanilla CSS custom properties with `oklch()`, vanilla ES modules served as static files, pytest + Starlette `TestClient`.

---

### Task 1: Wire `ADVISORY_THEME_DEFAULT` env into `pages.py`

**Files:**
- Modify: `web/routes/pages.py`
- Modify: `tests/web/test_pages.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_pages.py`:

```python
def test_chat_page_theme_default_light_when_env_unset():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("ADVISORY_THEME_DEFAULT", None)
        client = TestClient(build_app())
        response = client.get("/")
    assert response.status_code == 200
    assert 'data-theme-default="light"' in response.text


def test_chat_page_theme_default_dark_when_env_set_dark():
    with patch.dict(os.environ, {"ADVISORY_THEME_DEFAULT": "dark"}):
        client = TestClient(build_app())
        response = client.get("/")
    assert response.status_code == 200
    assert 'data-theme-default="dark"' in response.text


def test_chat_page_theme_default_falls_back_to_light_for_invalid_value():
    with patch.dict(os.environ, {"ADVISORY_THEME_DEFAULT": "neon-purple"}):
        client = TestClient(build_app())
        response = client.get("/")
    assert response.status_code == 200
    assert 'data-theme-default="light"' in response.text
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/web/test_pages.py -v`
Expected: the three new tests FAIL — `theme_default` context key does not yet exist and the template does not render `data-theme-default`.

- [ ] **Step 3: Add `_theme_default()` and pass it to the template**

Replace `web/routes/pages.py` with:

```python
import os

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="web/templates")

_VALID_THEMES = {"light", "dark"}


def _debug_ui_enabled() -> bool:
    return os.environ.get("ADVISORY_DEBUG_UI") == "1"


def _theme_default() -> str:
    value = (os.environ.get("ADVISORY_THEME_DEFAULT") or "").strip().lower()
    return value if value in _VALID_THEMES else "light"


@router.get("/")
def chat_page(request: Request):
    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "page_title": "Student Advisory Chat",
            "debug_ui_enabled": _debug_ui_enabled(),
            "theme_default": _theme_default(),
        },
    )
```

- [ ] **Step 4: Render `data-theme-default` on `<html>` in `base.html`**

Edit `web/templates/base.html`. Change the opening `<html lang="vi">` line to:

```html
<html lang="vi" data-theme-default="{{ theme_default }}">
```

- [ ] **Step 5: Run the tests**

Run: `pytest tests/web/test_pages.py -v`
Expected: all 5 tests PASS (the 2 existing + the 3 new).

- [ ] **Step 6: Commit**

```powershell
git add web/routes/pages.py web/templates/base.html tests/web/test_pages.py
git commit -m @'
feat(web): pipe ADVISORY_THEME_DEFAULT through to template

Reads the env once per request, validates against {light, dark}, falls back to light, and exposes it to Jinja as `theme_default` so the upcoming FOUC-init script has a server-side default to fall back on before localStorage/system preference.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 2: Create `tokens.css` (light + dark oklch design tokens)

**Files:**
- Create: `web/static/css/tokens.css`

- [ ] **Step 1: Create the file with the spec's verbatim token values**

Create `web/static/css/tokens.css`:

```css
:root {
  /* Typography */
  --font-sans: ui-sans-serif, system-ui, "Segoe UI", -apple-system, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --text-xs: 12px; --text-sm: 13px; --text-base: 14px; --text-md: 15px;
  --text-lg: 17px; --text-xl: 20px; --text-2xl: 24px;
  --leading-tight: 1.3; --leading-base: 1.55;

  /* Spacing (4px base) */
  --space-1: 4px;  --space-2: 8px;  --space-3: 12px;
  --space-4: 16px; --space-5: 24px; --space-6: 32px; --space-8: 48px;

  /* Radius */
  --radius-sm: 4px; --radius-md: 6px; --radius-lg: 10px; --radius-pill: 999px;

  /* Layout */
  --col-left: 280px; --col-right: 320px; --header-h: 56px;
  --bubble-max: 70%;

  /* Motion */
  --transition-fast: 120ms ease;
  --transition-base: 200ms ease;

  /* Shadow */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.06);
}

[data-theme="light"] {
  --surface-1: oklch(99% 0.003 250);   /* page bg */
  --surface-2: oklch(97% 0.005 250);   /* panel bg */
  --surface-3: oklch(94% 0.008 250);   /* card bg, hover */
  --surface-4: oklch(89% 0.012 250);   /* borders */
  --text-1:    oklch(20% 0.02 250);
  --text-2:    oklch(40% 0.02 250);
  --text-3:    oklch(60% 0.015 250);
  --accent-1:        oklch(55% 0.18 255);
  --accent-1-hover:  oklch(50% 0.18 255);
  --accent-1-contrast: oklch(99% 0 0);
  --positive:  oklch(55% 0.15 145);
  --warning:   oklch(70% 0.16 75);
  --negative:  oklch(55% 0.20 25);
  --user-bubble:  oklch(95% 0.04 145);
  --assistant-bg: var(--surface-2);
}

[data-theme="dark"] {
  --surface-1: oklch(15% 0.01 250);
  --surface-2: oklch(19% 0.012 250);
  --surface-3: oklch(24% 0.015 250);
  --surface-4: oklch(32% 0.018 250);
  --text-1:    oklch(95% 0.005 250);
  --text-2:    oklch(75% 0.01 250);
  --text-3:    oklch(55% 0.012 250);
  --accent-1:        oklch(70% 0.18 255);
  --accent-1-hover:  oklch(75% 0.18 255);
  --accent-1-contrast: oklch(15% 0.01 250);
  --positive:  oklch(70% 0.15 145);
  --warning:   oklch(78% 0.16 75);
  --negative:  oklch(70% 0.20 25);
  --user-bubble:  oklch(28% 0.05 145);
  --assistant-bg: var(--surface-2);
}
```

- [ ] **Step 2: Manual visual check (file served by static mount)**

Run uvicorn locally:
```powershell
uvicorn web.app:build_app --factory --reload --port 8000
```
Open `http://127.0.0.1:8000/static/css/tokens.css` in the browser. Expected: the raw CSS file is served (200 OK, content matches what was written). It is not yet referenced by any HTML — that happens in Task 3.

- [ ] **Step 3: Commit**

```powershell
git add web/static/css/tokens.css
git commit -m @'
feat(ui): add oklch design tokens (light + dark)

Introduces the design-system foundation: typography scale, 4px spacing, radii, layout vars, motion + shadow tokens, and full light/dark oklch palette keyed off `[data-theme=...]`. Consumed by chat.css and later module CSS in subsequent slices.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 3: Update `base.html` (load tokens, FOUC init, marked CDN, module script)

**Files:**
- Modify: `web/templates/base.html`

- [ ] **Step 1: Rewrite `base.html`**

Replace the full contents of `web/templates/base.html` with:

```html
<!DOCTYPE html>
<html lang="vi" data-theme-default="{{ theme_default }}">
  <head>
    <meta charset="utf-8" />
    <title>{{ page_title }}</title>
    <script>
      (function () {
        try {
          var root = document.documentElement;
          var stored = window.localStorage.getItem("theme");
          var fallback = root.dataset.themeDefault || "light";
          var sys = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
          var theme = stored || fallback || sys;
          root.dataset.theme = theme;
        } catch (e) {
          document.documentElement.dataset.theme = "light";
        }
      })();
    </script>
    <link rel="stylesheet" href="/static/css/tokens.css" />
    <link rel="stylesheet" href="/static/css/chat.css" />
    <script
      src="https://cdn.jsdelivr.net/npm/marked@13.0.3/marked.min.js"
      integrity="sha384-Y9w0XdJZxYgGd2nFXFRz1XQXl3GBu/zZyJfQqRJZN+J8u8wVw0nFqK3Y4lTAaVRn"
      crossorigin="anonymous"
      defer
    ></script>
  </head>
  <body>
    {% block body %}{% endblock %}
    <script type="module" src="/static/js/chat.js"></script>
  </body>
</html>
```

**Notes for the engineer:**
- The inline FOUC-guard script reads `<html data-theme-default="...">` (set by the template) so the server-side default flows in. Order of precedence inside the script: `localStorage("theme")` > `data-theme-default` > system pref.
- The `tokens.css` link MUST come before `chat.css` so `chat.css` can `var(--surface-1)` etc.
- The `marked@13.0.3` SRI hash above is a placeholder. If it fails browser SRI verification, regenerate it with:
  ```powershell
  curl https://cdn.jsdelivr.net/npm/marked@13.0.3/marked.min.js | openssl dgst -sha384 -binary | openssl base64 -A
  ```
  and replace the `integrity="..."` value. Do not block the slice on this — `marked` is only consumed by Slice 03.
- `chat.js` is now `type="module"` so Slice 02+ modules can `import` it.

- [ ] **Step 2: Run the existing page tests**

Run: `pytest tests/web/test_pages.py -v`
Expected: all 5 tests still PASS — `data-theme-default` is rendered by the template.

- [ ] **Step 3: Manual visual check (no theme toggle yet)**

```powershell
uvicorn web.app:build_app --factory --reload --port 8000
```
Open `http://127.0.0.1:8000/` and inspect the DOM in devtools. Expected:
- `<html lang="vi" data-theme-default="light" data-theme="light">` (or `data-theme="dark"` if your OS prefers dark).
- Network tab shows `tokens.css` 200 OK loaded before `chat.css`.
- Network tab shows the `marked.min.js` CDN request (may show as deferred). If the SRI hash mismatches you will see a console error — regenerate per the note above.
- `chat.js` is loaded with `type="module"`.

- [ ] **Step 4: Commit**

```powershell
git add web/templates/base.html
git commit -m @'
feat(web): load tokens.css, FOUC-guard theme init, marked CDN, module chat.js

Adds the foundation plumbing: inline <head> script sets `data-theme` from localStorage > server default > system pref before any stylesheet paints (no flash); tokens.css loads before chat.css; marked@13.0.3 is fetched from jsDelivr with SRI hash (consumed in slice 03); chat.js converted to type=module so later slices can split into ES modules.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 4: Add header bar + theme toggle button to `chat.html`

**Files:**
- Modify: `web/templates/chat.html`

**Slice scope reminder:** Slice 02 will fully rewrite this template into a 3-column grid. Here we only add a sticky 56px header bar at the very top with title + theme-toggle button; the existing 2-column body (chat panel + summary panel + hidden trace panel) stays exactly as it is.

- [ ] **Step 1: Wrap the existing main in a new shell with a header bar**

Replace the entire contents of `web/templates/chat.html` with:

```html
{% extends "base.html" %}
{% block body %}
<div class="app-shell">
  <header class="app-header" role="banner">
    <div class="app-header__brand">
      <span class="app-header__title">Tư vấn tuyển sinh AI</span>
    </div>
    <div class="app-header__actions">
      <button
        id="theme-toggle"
        type="button"
        class="icon-button"
        aria-label="Chuyển chế độ sáng/tối"
        title="Chuyển chế độ sáng/tối"
      >
        <span class="theme-toggle__icon theme-toggle__icon--light" aria-hidden="true">☀</span>
        <span class="theme-toggle__icon theme-toggle__icon--dark" aria-hidden="true">🌙</span>
      </button>
    </div>
  </header>

  <main class="chat-shell" data-debug-ui="{{ 'true' if debug_ui_enabled else 'false' }}">
    <section class="chat-panel">
      <header class="chat-header">
        <h1>Student Advisory Chat</h1>
        <button id="reset-session" type="button" class="secondary-button">Bắt đầu lại</button>
      </header>

      <div id="chat-status" class="chat-status" aria-live="polite"></div>
      <div id="chat-transcript" class="chat-transcript" aria-live="polite"></div>

      <form id="chat-form" class="chat-form">
        <label for="chat-input" class="sr-only">Nội dung tin nhắn</label>
        <textarea
          id="chat-input"
          name="content"
          rows="4"
          placeholder="Ví dụ: Em muốn học CNTT ở Hà Nội năm 2026, dự kiến được 27 điểm."
        ></textarea>
        <div class="chat-actions">
          <button id="send-button" type="submit">Gửi</button>
        </div>
      </form>
    </section>

    <aside class="summary-panel">
      <section>
        <h2>Hồ sơ tạm thời</h2>
        <div id="profile-summary"></div>
      </section>
      <section>
        <h2>Khuyến nghị mới nhất</h2>
        <div id="recommendation-panel"></div>
      </section>
    </aside>

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
  </main>
</div>
{% endblock %}
```

- [ ] **Step 2: Append header bar styles to `chat.css`**

Append to `web/static/css/chat.css`:

```css
/* ===== App shell + header (slice 01 foundation) ===== */

.app-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.app-header {
  position: sticky;
  top: 0;
  z-index: 10;
  height: var(--header-h, 56px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-4, 16px);
  background: var(--surface-2);
  border-bottom: 1px solid var(--surface-4);
  color: var(--text-1);
}

.app-header__title {
  font-family: var(--font-sans);
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-1);
}

.app-header__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.icon-button {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--surface-4);
  background: var(--surface-1);
  color: var(--text-1);
  border-radius: var(--radius-md);
  cursor: pointer;
  font-size: var(--text-md);
  line-height: 1;
  padding: 0;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}

.icon-button:hover {
  background: var(--surface-3);
  border-color: var(--text-3);
}

.icon-button:focus-visible {
  outline: 2px solid var(--accent-1);
  outline-offset: 2px;
}

/* Show only the icon that matches the *opposite* of the active theme,
   i.e. the icon represents "click to switch to this mode". */
.theme-toggle__icon { display: none; }
[data-theme="light"] .theme-toggle__icon--dark  { display: inline; }
[data-theme="dark"]  .theme-toggle__icon--light { display: inline; }
```

- [ ] **Step 3: Run page tests**

Run: `pytest tests/web/test_pages.py -v`
Expected: PASS — markup additions don't break existing assertions (`data-debug-ui` and `data-theme-default` still render).

- [ ] **Step 4: Manual visual check**

Reload `http://127.0.0.1:8000/`. Expected:
- A sticky bar appears at the top (~56px tall) with "Tư vấn tuyển sinh AI" on the left.
- A single 32x32 icon button on the right shows either `🌙` (in light mode) or `☀` (in dark mode).
- The existing 2-column chat body renders below, unchanged.
- Clicking the button does nothing yet — wiring happens in Task 5/6.

- [ ] **Step 5: Commit**

```powershell
git add web/templates/chat.html web/static/css/chat.css
git commit -m @'
feat(ui): add sticky header bar with theme-toggle button (no behavior yet)

Wraps the existing chat layout in an app-shell with a 56px sticky header carrying the product title and a theme-toggle icon button. The button is intentionally inert in this commit — handler wiring lands in the theme.js module + chat.js orchestrator step. The rest of the chat body remains the legacy 2-column layout; the full 3-column rewrite is slice 02.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 5: Create `theme.js` ES module

**Files:**
- Create: `web/static/js/modules/theme.js`

- [ ] **Step 1: Create the module**

Create `web/static/js/modules/theme.js` with:

```javascript
// web/static/js/modules/theme.js
//
// Theme management for the advisory-agent chat UI.
//
// The inline FOUC-guard script in base.html has already set
// `<html data-theme="light|dark">` before this module loads. This module:
//   - wires the #theme-toggle button click,
//   - listens to system prefers-color-scheme changes (only honors them
//     when the user has not made an explicit choice in localStorage),
//   - exposes toggleTheme() for programmatic flips.

const STORAGE_KEY = "theme";
const VALID = new Set(["light", "dark"]);

function readStored() {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return VALID.has(v) ? v : null;
  } catch (e) {
    return null;
  }
}

function writeStored(theme) {
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch (e) {
    /* ignore quota / private-mode errors */
  }
}

function applyTheme(theme) {
  if (!VALID.has(theme)) return;
  document.documentElement.dataset.theme = theme;
  document.dispatchEvent(
    new CustomEvent("theme-change", { detail: { theme } })
  );
}

export function toggleTheme() {
  const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const next = current === "dark" ? "light" : "dark";
  applyTheme(next);
  writeStored(next);
  return next;
}

export function initTheme() {
  const button = document.getElementById("theme-toggle");
  if (button) {
    button.addEventListener("click", () => {
      toggleTheme();
    });
  }

  // Honor system preference changes only when the user has not chosen.
  if (typeof window.matchMedia === "function") {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (event) => {
      if (readStored() !== null) return; // explicit choice wins
      applyTheme(event.matches ? "dark" : "light");
    };
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", handler);
    } else if (typeof mq.addListener === "function") {
      // Safari < 14 fallback
      mq.addListener(handler);
    }
  }
}
```

- [ ] **Step 2: Verify the file is served as a JS module**

Run: `uvicorn web.app:build_app --factory --reload --port 8000`
Open `http://127.0.0.1:8000/static/js/modules/theme.js` — expected: 200 OK, content matches.

- [ ] **Step 3: Commit**

```powershell
git add web/static/js/modules/theme.js
git commit -m @'
feat(ui): add theme.js module (initTheme + toggleTheme)

Pure ES module: wires #theme-toggle click, listens to prefers-color-scheme media changes (only when localStorage has no explicit choice), and dispatches a `theme-change` CustomEvent so future modules can react. Imported by chat.js in the next step.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 6: Wire `chat.js` to import + call `initTheme()`

**Files:**
- Modify: `web/static/js/chat.js`

- [ ] **Step 1: Add the import at the top of `chat.js`**

In `web/static/js/chat.js`, prepend the following line as the very first line of the file (before the existing `const SESSION_KEY = ...`):

```javascript
import { initTheme } from "./modules/theme.js";
```

- [ ] **Step 2: Call `initTheme()` early inside `DOMContentLoaded`**

Find the existing handler:

```javascript
document.addEventListener("DOMContentLoaded", async () => {
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const resetButton = document.getElementById("reset-session");

  if (debugUiEnabled()) {
    showTracePanel();
  }
```

Change it to call `initTheme()` immediately after grabbing the elements:

```javascript
document.addEventListener("DOMContentLoaded", async () => {
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const resetButton = document.getElementById("reset-session");

  initTheme();

  if (debugUiEnabled()) {
    showTracePanel();
  }
```

- [ ] **Step 3: Manual end-to-end check (the key smoke test for this slice)**

Restart uvicorn (no env flag needed):
```powershell
uvicorn web.app:build_app --factory --reload --port 8000
```
Open `http://127.0.0.1:8000/` and exercise:

1. Click the header `🌙` (or `☀`) button — the page background should swap immediately (light <-> dark). The icon flips.
2. Reload the page — the previously chosen theme persists (proves `localStorage` write + FOUC-guard read).
3. Open devtools Application > Local Storage, delete the `theme` key, reload — theme should now reflect either `ADVISORY_THEME_DEFAULT` env (unset → `light`) or your OS `prefers-color-scheme` (the FOUC guard prefers `data-theme-default` over `sys`; the matchMedia listener only kicks in when no choice is stored).
4. Open two tabs. In tab A, toggle to dark; in tab B, do nothing — toggling in A does not affect B until B is reloaded (acceptable; multi-tab sync is out of scope for this slice).

Also check the devtools console — no errors about module imports or SRI mismatch (if SRI mismatches, regenerate per Task 3 Step 1 note).

- [ ] **Step 4: Commit**

```powershell
git add web/static/js/chat.js
git commit -m @'
feat(ui): wire chat.js to initialize theme module on DOM ready

Imports initTheme from the new theme module and calls it early in DOMContentLoaded so the header theme-toggle button becomes live. chat.js is now a true ES module (loaded via `<script type=module>` from slice 01 Task 3).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 7: Light touch on `chat.css` — body uses token surface/text

**Files:**
- Modify: `web/static/css/chat.css`

**Slice scope reminder:** Do NOT restyle the chat panels, transcript, bubbles, or trace cards here. Slice 02 owns the full chat.css rewrite. The only change here is the global `body` rule so the dark-mode background/text actually flips when the user toggles.

- [ ] **Step 1: Replace the body rule**

In `web/static/css/chat.css`, find the very first rule:

```css
body {
  margin: 0;
  font-family: "Segoe UI", sans-serif;
  background: #f6f8fb;
  color: #1f2933;
}
```

Replace it with:

```css
body {
  margin: 0;
  font-family: var(--font-sans);
  background: var(--surface-1);
  color: var(--text-1);
}
```

- [ ] **Step 2: Manual visual check**

Reload `http://127.0.0.1:8000/`. Expected:
- In light mode: page background is near-white (`oklch(99% 0.003 250)`), text near-black. Existing white panels remain readable.
- Toggle to dark: page background flips to deep blue-black (`oklch(15% 0.01 250)`), text flips to near-white. The white panels still render white — that's expected and will be addressed in Slice 02.
- The sticky header bar and theme-toggle button both flip cleanly (they already use tokens from Task 4).

- [ ] **Step 3: Commit**

```powershell
git add web/static/css/chat.css
git commit -m @'
feat(ui): consume surface/text tokens on body for theme-aware bg

Minimal token wiring so the dark/light toggle has visible effect on the page background and primary text color. Inner panel restyling is deferred to slice 02 (full chat.css rewrite); this keeps slice 01 strictly foundation work.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 8: Manual smoke + automated test sweep

**Files:**
- (none modified — verification only)

- [ ] **Step 1: Run the full web test suite**

```powershell
pytest tests/web -v
```
Expected: every test passes (including `test_pages.py`, the existing chat template tests, and trace endpoint tests from slice 04). If anything fails, fix before declaring the slice done.

- [ ] **Step 2: Run the broader unit suite**

```powershell
pytest -m "not integration" -q
```
Expected: PASS. (Integration tests requiring Docker DB are not in scope for this slice.)

- [ ] **Step 3: Manual smoke checklist**

Bring up the app:
```powershell
uvicorn web.app:build_app --factory --reload --port 8000
```

Walk through these in a single browser session:

1. Fresh load, no `localStorage` `theme` key, env unset → page renders in `light` (per `data-theme-default`).
2. Click `🌙` → instantly flips to dark; icon swaps to `☀`.
3. Reload → still dark (FOUC guard reads `localStorage`).
4. Manually clear `localStorage` `theme` key, reload → falls back to `light` (server default beats system pref per the FOUC script order).
5. Restart uvicorn with `$env:ADVISORY_THEME_DEFAULT="dark"`, clear `localStorage`, reload → page loads in dark.
6. With no `localStorage` `theme` key, toggle OS color scheme (System Settings > Personalization > Colors on Windows) → because the server default is set, system pref does not override. Acceptable: the matchMedia listener in `theme.js` only acts when both localStorage is unset AND the server default is being ignored — this matches the spec.
7. Devtools Network tab: confirm `tokens.css` returns 200 and is loaded before `chat.css`; `marked@13.0.3` request returns 200 from jsDelivr with no SRI console error.
8. Devtools Console: no JS errors at any point.

- [ ] **Step 4: No commit needed for verification-only task**

If any smoke step fails, file a follow-up commit in the appropriate task above (e.g., SRI regeneration → amend Task 3 file). Do not introduce a "fix" commit here.

---

## Slice 01 Done When

- [ ] `pytest tests/web -v` is green.
- [ ] `web/static/css/tokens.css` exists and is served (`GET /static/css/tokens.css` → 200) with the spec's light + dark oklch palette.
- [ ] `<html>` carries both `data-theme-default="{light|dark}"` (from the server) and `data-theme="{light|dark}"` (set by the inline FOUC script before paint).
- [ ] Setting `ADVISORY_THEME_DEFAULT=dark` and clearing `localStorage` makes a fresh page load render in dark.
- [ ] Clicking `#theme-toggle` swaps themes instantly and persists across reload via `localStorage`.
- [ ] The page has a sticky 56px header bar at the top with the product title on the left and the theme-toggle button on the right; the rest of the body is the legacy 2-column layout (no other regressions).
- [ ] `chat.js` is loaded via `<script type="module">` and successfully imports `./modules/theme.js`.
- [ ] `marked@13.0.3` is fetched from the jsDelivr CDN with `integrity` + `crossorigin="anonymous"` + `defer` (used by Slice 03; SRI hash regenerated if needed).
- [ ] No console errors, no visible FOUC on first paint (refresh-spam test).
