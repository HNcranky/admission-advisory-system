# Slice 05 — States, Tests & Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add empty-state, skeleton, loading-dot, toast, mobile-drawer-polish, and help-popover layers that turn the functional UI into a finished UI; update tests and `QUICKSTART.md` so the manual smoke checklist from spec §12 passes end-to-end.

**Architecture:** All polish is presentation-layer additions. Empty states and skeletons render inside existing module functions (`renderTranscript`, `renderProfileSummary`, `renderRecommendation`). The toast module is a new self-contained ES module with no dependencies. Mobile drawer polish reuses the existing `openDrawer`/`closeDrawer` from `layout.js`. The help popover uses a native `<dialog>` element with server-passed `app_version` read once from `pyproject.toml`.

**Tech Stack:** Jinja2, FastAPI, vanilla JS (ES modules), CSS custom properties, pytest, PowerShell for local dev.

---

### Task 1: Greeting empty state for the chat transcript

**Files:**
- Modify: `web/static/js/modules/messages.js`
- Modify: `web/static/js/chat.js`
- Modify: `web/static/css/chat.css`

- [ ] **Step 1: Add `renderGreeting` to `messages.js`**

Append a new export to `web/static/js/modules/messages.js`:

```javascript
const GREETING_PROMPTS = [
  "Em muốn học ngành CNTT, điểm thi 25.",
  "Em ở Hà Nội, muốn học kinh tế ở trường công lập.",
  "Em đang phân vân giữa Bách Khoa và Kinh tế Quốc dân.",
];

export function renderGreeting(node) {
  if (!node) return;
  node.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "transcript-greeting";
  wrap.innerHTML = `
    <div class="transcript-greeting__icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
           stroke-linecap="round" stroke-linejoin="round" width="40" height="40">
        <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>
      </svg>
    </div>
    <p class="transcript-greeting__title">
      Xin chào! Hãy mô tả tình hình xét tuyển của em...
    </p>
    <ul class="transcript-greeting__chips" role="list">
      ${GREETING_PROMPTS.map(
        (p) => `<li><button type="button" class="chip" data-prompt="${p.replace(/"/g, "&quot;")}">${p}</button></li>`,
      ).join("")}
    </ul>
  `;
  node.append(wrap);
}
```

Then update `renderTranscript` so it calls `renderGreeting(node)` when `messages` is empty or contains only a single `system` welcome:

```javascript
export function renderTranscript(node, messages) {
  if (!node) return;
  const visible = (messages || []).filter((m) => m && m.kind !== "system");
  if (visible.length === 0) {
    renderGreeting(node);
    return;
  }
  node.innerHTML = "";
  visible.forEach((m) => appendMessage(node, m));
}
```

- [ ] **Step 2: Wire chip clicks in `chat.js`**

In `web/static/js/chat.js`, after the existing composer wiring inside `DOMContentLoaded`, add:

```javascript
  document.getElementById("chat-transcript")?.addEventListener("click", (event) => {
    const chip = event.target.closest(".chip[data-prompt]");
    if (!chip) return;
    const textarea = document.getElementById("composer-input");
    if (!textarea) return;
    textarea.value = chip.dataset.prompt;
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    textarea.focus();
  });
```

- [ ] **Step 3: Add CSS for the greeting card**

Append to `web/static/css/chat.css`:

```css
/* ===== Greeting empty state ===== */

.transcript-greeting {
  margin: auto;
  max-width: 480px;
  padding: var(--space-6) var(--space-5);
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  color: var(--text-2);
}

.transcript-greeting__icon {
  color: var(--accent-1);
  background: var(--surface-3);
  padding: var(--space-3);
  border-radius: 999px;
  display: inline-flex;
}

.transcript-greeting__title {
  margin: 0;
  font-size: var(--text-md);
  color: var(--text-1);
}

.transcript-greeting__chips {
  list-style: none;
  padding: 0;
  margin: var(--space-2) 0 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  width: 100%;
}

.chip {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  background: var(--surface-2);
  color: var(--text-1);
  border: 1px solid var(--surface-4);
  border-radius: var(--radius-md);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background var(--transition-fast), border-color var(--transition-fast);
}
.chip:hover { background: var(--surface-3); border-color: var(--accent-1); }
.chip:focus-visible { outline: 2px solid var(--accent-1); outline-offset: 2px; }
```

- [ ] **Step 4: Manual smoke**

```powershell
uvicorn web.app:build_app --factory --reload --port 8000
```

Open `http://127.0.0.1:8000/` in an incognito window (fresh `localStorage`). Expected: the chat transcript shows the centered icon, welcome text, and 3 chips. Click a chip → its text fills the composer textarea and focus moves to it. Type a message → the greeting disappears.

- [ ] **Step 5: Commit**

```powershell
git add web/static/js/modules/messages.js web/static/js/chat.js web/static/css/chat.css
git commit -m "$(cat <<'EOF'
feat(ui): greeting empty state with example chips in chat transcript

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Profile + recommendation empty-state text

**Files:**
- Modify: `web/static/js/chat.js` (or `web/static/js/modules/messages.js` if that's where profile/recommendation render lives — check first)
- Modify: `web/static/css/chat.css`

- [ ] **Step 1: Inspect current renderers**

```powershell
Get-Content web/static/js/chat.js | Select-String -Pattern "profile|recommendation|assistant_result" -Context 1,3
```

Identify the function that writes into `#profile-summary` and `#recommendation-card` (after slice 04 refactor, likely in `chat.js` or a module).

- [ ] **Step 2: Add empty-state branches**

In the profile-summary renderer, when `profile_state_json` has no truthy fields (i.e. every value is `null`, `""`, or empty list/object):

```javascript
function profileIsEmpty(profile) {
  if (!profile) return true;
  return Object.values(profile).every(
    (v) => v == null || v === "" || (Array.isArray(v) && v.length === 0),
  );
}

function renderProfileSummary(node, profile) {
  if (!node) return;
  if (profileIsEmpty(profile)) {
    node.innerHTML =
      '<p class="card-empty">Hồ sơ sẽ tự cập nhật khi em trò chuyện.</p>';
    return;
  }
  // ...existing row-rendering logic...
}
```

In the recommendation renderer, when no `assistant_result` exists AND session status is not `running`/`queued`:

```javascript
function renderRecommendation(node, result, status) {
  if (!node) return;
  if (!result && status !== "running" && status !== "queued") {
    node.innerHTML = '<p class="card-empty">Chưa có khuyến nghị.</p>';
    return;
  }
  // ...existing markdown-render logic (or skeleton from Task 3)...
}
```

- [ ] **Step 3: Add CSS for `.card-empty`**

Append to `web/static/css/chat.css`:

```css
.card-empty {
  margin: 0;
  color: var(--text-3);
  font-style: italic;
  font-size: var(--text-sm);
}
```

- [ ] **Step 4: Manual smoke**

Reload `/` in an incognito window. Expected: profile card shows "Hồ sơ sẽ tự cập nhật khi em trò chuyện." Recommendation card shows "Chưa có khuyến nghị."

- [ ] **Step 5: Commit**

```powershell
git add web/static/js/chat.js web/static/css/chat.css
git commit -m "$(cat <<'EOF'
feat(ui): muted empty-state text for profile and recommendation cards

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Skeleton pulse for the recommendation card during a run

**Files:**
- Modify: `web/static/js/chat.js`
- Modify: `web/static/css/chat.css`

- [ ] **Step 1: Add skeleton render branch**

Update the recommendation renderer:

```javascript
function renderRecommendation(node, result, status) {
  if (!node) return;
  if (!result && (status === "running" || status === "queued")) {
    node.innerHTML = `
      <div class="skeleton" aria-hidden="true">
        <div class="skeleton-line skeleton-line--100"></div>
        <div class="skeleton-line skeleton-line--85"></div>
        <div class="skeleton-line skeleton-line--60"></div>
      </div>
      <span class="visually-hidden">Đang soạn khuyến nghị...</span>`;
    return;
  }
  if (!result) {
    node.innerHTML = '<p class="card-empty">Chưa có khuyến nghị.</p>';
    return;
  }
  // ...existing markdown render...
}
```

- [ ] **Step 2: Add CSS for skeleton + pulse**

Append to `web/static/css/chat.css`:

```css
/* ===== Skeleton pulse ===== */

.skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.skeleton-line {
  height: 10px;
  border-radius: var(--radius-sm);
  background: var(--surface-3);
  animation: pulse 1.6s ease-in-out infinite;
}
.skeleton-line--100 { width: 100%; }
.skeleton-line--85  { width: 85%;  }
.skeleton-line--60  { width: 60%;  }

@keyframes pulse {
  0%, 100% { opacity: 0.4; }
  50%      { opacity: 0.7; }
}

.visually-hidden {
  position: absolute;
  width: 1px; height: 1px;
  padding: 0; margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
```

- [ ] **Step 3: Manual smoke**

Start the full stack (`docker compose up -d --wait db`, set `GEMINI_API_KEY`, start uvicorn). Send a complete profile to trigger a run. Expected: while `status === "running"`, the recommendation card shows 3 pulsing grey bars. As soon as `assistant_result` arrives, the markdown render replaces them.

- [ ] **Step 4: Commit**

```powershell
git add web/static/js/chat.js web/static/css/chat.css
git commit -m "$(cat <<'EOF'
feat(ui): skeleton pulse in recommendation card while run is in flight

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Loading dots for `chat-status[data-tone="pending"]`

**Files:**
- Modify: `web/static/css/chat.css`

- [ ] **Step 1: Add pure-CSS dot animation**

Append to `web/static/css/chat.css`:

```css
/* ===== Loading dots on chat-status ===== */

#chat-status[data-tone="pending"]::after {
  content: "";
  display: inline-block;
  width: 1.2em;
  text-align: left;
  margin-left: 2px;
  animation: loading-dots 1.4s steps(4, end) infinite;
}

@keyframes loading-dots {
  0%   { content: ""; }
  25%  { content: "."; }
  50%  { content: ".."; }
  75%  { content: "..."; }
  100% { content: ""; }
}
```

Note: the `content` keyframe approach works in all modern evergreen browsers (Chrome 79+, Firefox 87+, Safari 14+) which match spec §4 browser target.

- [ ] **Step 2: Manual smoke**

Trigger a run. Expected: while the status reads `Đang phân tích` with `data-tone="pending"`, three dots animate after it (`.`, `..`, `...`). When status transitions to `success` or `error`, the dots stop.

- [ ] **Step 3: Commit**

```powershell
git add web/static/css/chat.css
git commit -m "$(cat <<'EOF'
feat(ui): animated dots after chat status while pending

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Toast module + container + CSS

**Files:**
- Create: `web/static/js/modules/toasts.js`
- Modify: `web/templates/chat.html`
- Modify: `web/static/css/chat.css`

- [ ] **Step 1: Create `toasts.js`**

Write `web/static/js/modules/toasts.js`:

```javascript
const STACK_ID = "toast-stack";
const MAX_TOASTS = 3;
const DEFAULT_TIMEOUT_MS = 4000;
const ERROR_TIMEOUT_MS = 8000;

function stack() {
  return document.getElementById(STACK_ID);
}

function evictOldest(list) {
  while (list.children.length >= MAX_TOASTS) {
    const first = list.firstElementChild;
    if (!first) break;
    first.remove();
  }
}

function dismiss(el) {
  if (!el || el.dataset.dismissing === "1") return;
  el.dataset.dismissing = "1";
  el.classList.add("toast--leaving");
  window.setTimeout(() => el.remove(), 200);
}

/**
 * Show a non-blocking toast.
 * @param {string} message
 * @param {{ variant?: 'info'|'warning'|'error', timeoutMs?: number }} [opts]
 */
export function toast(message, opts = {}) {
  const list = stack();
  if (!list) return;

  const variant = opts.variant || "info";
  const timeoutMs =
    opts.timeoutMs != null
      ? opts.timeoutMs
      : variant === "error"
      ? ERROR_TIMEOUT_MS
      : DEFAULT_TIMEOUT_MS;

  evictOldest(list);

  const item = document.createElement("li");
  item.className = `toast toast--${variant}`;
  item.setAttribute("role", variant === "error" ? "alert" : "status");

  const body = document.createElement("span");
  body.className = "toast__body";
  body.textContent = message;
  item.append(body);

  if (variant === "error") {
    const close = document.createElement("button");
    close.type = "button";
    close.className = "toast__close";
    close.setAttribute("aria-label", "Đóng");
    close.textContent = "×";
    close.addEventListener("click", () => dismiss(item));
    item.append(close);
  }

  list.append(item);

  if (timeoutMs > 0) {
    window.setTimeout(() => dismiss(item), timeoutMs);
  }
}
```

- [ ] **Step 2: Add the container to `chat.html`**

In `web/templates/chat.html`, immediately before the closing `</body>` tag, add:

```html
  <ol id="toast-stack" aria-live="polite" aria-atomic="false"></ol>
```

- [ ] **Step 3: Add CSS for toasts**

Append to `web/static/css/chat.css`:

```css
/* ===== Toasts ===== */

#toast-stack {
  position: fixed;
  top: calc(var(--header-h) + var(--space-3));
  right: var(--space-4);
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  z-index: 60;
  pointer-events: none;
  max-width: min(360px, calc(100vw - var(--space-5)));
}

.toast {
  pointer-events: auto;
  background: var(--surface-2);
  color: var(--text-1);
  border: 1px solid var(--surface-4);
  border-left: 3px solid var(--accent-1);
  border-radius: var(--radius-md);
  padding: var(--space-2) var(--space-3);
  box-shadow: var(--shadow-md);
  font-size: var(--text-sm);
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  animation: toast-in 200ms ease;
}

.toast--info    { border-left-color: var(--accent-1); }
.toast--warning { border-left-color: var(--warning); }
.toast--error   { border-left-color: var(--negative); }

.toast--leaving { animation: toast-out 200ms ease forwards; }

.toast__body { flex: 1; line-height: var(--leading-base); }

.toast__close {
  background: transparent;
  border: 0;
  color: var(--text-2);
  font-size: 1.2em;
  line-height: 1;
  cursor: pointer;
  padding: 0 var(--space-1);
}
.toast__close:hover { color: var(--text-1); }

@keyframes toast-in {
  from { transform: translateX(20px); opacity: 0; }
  to   { transform: translateX(0);    opacity: 1; }
}
@keyframes toast-out {
  from { transform: translateX(0);    opacity: 1; }
  to   { transform: translateX(20px); opacity: 0; }
}
```

- [ ] **Step 4: Manual smoke**

Reload `/`. In devtools console:

```javascript
const { toast } = await import("/static/js/modules/toasts.js");
toast("Hello info");
toast("Hello warning", { variant: "warning" });
toast("Hello error", { variant: "error" });
```

Expected: three toasts slide in top-right, info/warning auto-dismiss after 4 s, error stays 8 s and has an `×` button.

- [ ] **Step 5: Commit**

```powershell
git add web/static/js/modules/toasts.js web/templates/chat.html web/static/css/chat.css
git commit -m "$(cat <<'EOF'
feat(ui): toast module with info/warning/error variants and stack cap of 3

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Wire toasts into network failure paths

**Files:**
- Modify: `web/static/js/chat.js`
- Modify: `web/static/js/modules/trace.js`

- [ ] **Step 1: Import in `chat.js`**

At the top of `web/static/js/chat.js`, add:

```javascript
import { toast } from "./modules/toasts.js";
```

- [ ] **Step 2: Wire `schedulePolling` failures**

Find the `catch` block inside `schedulePolling`'s tick function. Add the toast call at the start of the catch:

```javascript
    } catch (e) {
      toast("Mất kết nối, đang thử lại...", { variant: "warning" });
      // ...existing backoff retry logic...
    }
```

- [ ] **Step 3: Wire `createSession` failure**

Find the `createSession` (or equivalent bootstrap) call. Wrap or extend its error path:

```javascript
    try {
      currentSessionToken = await createSession();
    } catch (e) {
      toast("Không khởi tạo được phiên. Tải lại trang.", { variant: "error" });
      throw e;
    }
```

- [ ] **Step 4: Wire stale-token recovery toast**

Find the existing block that calls `window.localStorage.removeItem(SESSION_KEY)` after detecting a stale token. Immediately after the removal, add:

```javascript
      toast("Phiên cũ đã hết hạn, đã tạo phiên mới.", { variant: "info" });
```

- [ ] **Step 5: Wire trace polling toast with 10-second debounce**

In `web/static/js/modules/trace.js`, add at the top:

```javascript
import { toast } from "./toasts.js";

let lastTraceToastAt = 0;

function maybeToastTraceFailure() {
  const now = Date.now();
  if (now - lastTraceToastAt < 10_000) return;
  lastTraceToastAt = now;
  toast("Mất kết nối tới trace, đang thử lại...", { variant: "warning" });
}
```

In the trace polling tick's `catch` block, replace the silent retry with a call to `maybeToastTraceFailure()`:

```javascript
    } catch (e) {
      maybeToastTraceFailure();
      tracePollTimer = window.setTimeout(tick, TRACE_POLL_INTERVAL_MS * 2);
    }
```

- [ ] **Step 6: Manual smoke**

Start the full stack. Open devtools network tab. While a run is mid-flight, set the network condition to `Offline` for 2 s, then back to `Online`. Expected: a warning toast appears within 1.5 s of going offline; polling resumes silently when online (no second toast within 10 s).

- [ ] **Step 7: Commit**

```powershell
git add web/static/js/chat.js web/static/js/modules/trace.js
git commit -m "$(cat <<'EOF'
feat(ui): surface network and session errors via toast notifications

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Mobile drawer polish (backdrop, Escape, focus, animation, body lock)

**Files:**
- Modify: `web/templates/chat.html`
- Modify: `web/static/js/modules/layout.js`
- Modify: `web/static/css/chat.css`

- [ ] **Step 1: Add backdrop element**

In `web/templates/chat.html`, immediately after the opening `<body>` tag (or alongside the `chat-shell` root), add:

```html
  <div class="drawer-backdrop" id="drawer-backdrop" hidden></div>
```

- [ ] **Step 2: Update `layout.js` open/close**

In `web/static/js/modules/layout.js`, replace the existing `openDrawer` / `closeDrawer` implementations:

```javascript
let activeDrawer = null;
let drawerOpener = null;
let escListener = null;

function backdrop() {
  return document.getElementById("drawer-backdrop");
}

export function openDrawer(side) {
  const panel = document.getElementById(`${side}-panel`);
  if (!panel) return;
  drawerOpener = document.activeElement;
  activeDrawer = panel;
  panel.classList.add("panel--drawer-open");
  document.body.classList.add("drawer-open");
  const bd = backdrop();
  if (bd) {
    bd.hidden = false;
    bd.addEventListener("click", closeDrawer, { once: true });
  }
  escListener = (e) => { if (e.key === "Escape") closeDrawer(); };
  document.addEventListener("keydown", escListener);
  const closeBtn = panel.querySelector(".panel__drawer-close");
  if (closeBtn) closeBtn.focus();
}

export function closeDrawer() {
  if (!activeDrawer) return;
  activeDrawer.classList.remove("panel--drawer-open");
  document.body.classList.remove("drawer-open");
  const bd = backdrop();
  if (bd) bd.hidden = true;
  if (escListener) {
    document.removeEventListener("keydown", escListener);
    escListener = null;
  }
  if (drawerOpener && typeof drawerOpener.focus === "function") {
    drawerOpener.focus();
  }
  activeDrawer = null;
  drawerOpener = null;
}
```

Ensure each side panel has a `<button class="panel__drawer-close" aria-label="Đóng">×</button>` rendered inside it (add to `chat.html` if missing) so focus has a target.

- [ ] **Step 3: Add CSS for backdrop + animation + body lock**

Append to `web/static/css/chat.css`:

```css
/* ===== Mobile drawer polish ===== */

.drawer-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  z-index: 40;
  animation: backdrop-fade-in var(--transition-base);
}
.drawer-backdrop[hidden] { display: none; }

body.drawer-open { overflow: hidden; }

@media (max-width: 899px) {
  .profile-panel.panel--drawer-open,
  .trace-panel.panel--drawer-open {
    position: fixed;
    top: var(--header-h);
    bottom: 0;
    width: min(320px, 85vw);
    z-index: 50;
    background: var(--surface-1);
    box-shadow: var(--shadow-md);
    overflow-y: auto;
    animation: drawer-slide-in 200ms ease;
  }
  .profile-panel.panel--drawer-open { left: 0;  }
  .trace-panel.panel--drawer-open   { right: 0; }
}

.panel__drawer-close {
  position: absolute;
  top: var(--space-2);
  right: var(--space-2);
  background: transparent;
  border: 0;
  font-size: 1.4em;
  color: var(--text-2);
  cursor: pointer;
}

@keyframes backdrop-fade-in {
  from { opacity: 0; } to { opacity: 1; }
}
@keyframes drawer-slide-in {
  from { transform: translateX(-20px); opacity: 0; }
  to   { transform: translateX(0);     opacity: 1; }
}
.trace-panel.panel--drawer-open {
  /* mirror the slide direction for the right-side drawer */
  animation-name: drawer-slide-in-right;
}
@keyframes drawer-slide-in-right {
  from { transform: translateX(20px); opacity: 0; }
  to   { transform: translateX(0);    opacity: 1; }
}
```

- [ ] **Step 4: Manual smoke**

Resize browser < 900 px. Tap the profile drawer button → drawer slides in from left, backdrop fades, body scroll is locked. Press `Escape` → drawer closes, focus returns to the opener button. Repeat for trace panel from the right.

- [ ] **Step 5: Commit**

```powershell
git add web/templates/chat.html web/static/js/modules/layout.js web/static/css/chat.css
git commit -m "$(cat <<'EOF'
feat(ui): polish mobile drawers with backdrop, escape close, focus return, body lock

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Help popover with `app_version` from `pyproject.toml`

**Files:**
- Modify: `web/routes/pages.py`
- Modify: `web/templates/chat.html`
- Modify: `web/static/css/chat.css`
- Modify: `web/static/js/chat.js`
- Modify: `tests/web/test_pages.py`

- [ ] **Step 1: Write failing test for `app_version`**

In `tests/web/test_pages.py`, append:

```python
def test_chat_page_includes_app_version():
    from fastapi.testclient import TestClient
    from web.app import build_app

    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="help-popover"' in response.text
    # version string from pyproject.toml must appear inside the popover
    import tomllib
    from pathlib import Path
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject.get("project", {}).get("version", "dev")
    assert version in response.text
```

- [ ] **Step 2: Run to confirm failure**

```powershell
pytest tests/web/test_pages.py::test_chat_page_includes_app_version -v
```

Expected: FAIL — no `help-popover` markup or `app_version` context.

- [ ] **Step 3: Read app version in `pages.py`**

Edit `web/routes/pages.py`. At module top:

```python
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def _read_app_version() -> str:
    try:
        data = tomllib.loads(
            Path("pyproject.toml").read_text(encoding="utf-8")
        )
        return data.get("project", {}).get("version") or "dev"
    except Exception:
        return "dev"


_APP_VERSION = _read_app_version()
```

Pass it into the template context:

```python
return templates.TemplateResponse(
    request,
    "chat.html",
    {
        # ...existing keys...
        "app_version": _APP_VERSION,
    },
)
```

- [ ] **Step 4: Add help popover markup**

In `web/templates/chat.html`, find the header's help button (added in slice 01). Replace it with:

```html
        <button type="button" id="help-button" class="icon-button"
                aria-label="Trợ giúp" aria-haspopup="dialog"
                aria-controls="help-popover">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round" width="18" height="18"
               aria-hidden="true">
            <circle cx="12" cy="12" r="10"/>
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
            <line x1="12" y1="17" x2="12.01" y2="17"/>
          </svg>
        </button>
        <dialog id="help-popover" class="popover">
          <h3 class="popover__title">Tư vấn tuyển sinh AI</h3>
          <p class="popover__meta">Phiên bản {{ app_version }}</p>
          <p class="popover__desc">Trợ lý gợi ý ngành/trường dựa trên hồ sơ của em.</p>
          <hr class="popover__divider">
          <button type="button" id="reset-session" class="popover__link">
            Bắt đầu lại
          </button>
        </dialog>
```

Note: `id="reset-session"` MUST live inside the popover now (slice 01 had it on the header). Remove any duplicate `#reset-session` button from the header.

- [ ] **Step 5: Wire open/close in `chat.js`**

In `web/static/js/chat.js`, inside `DOMContentLoaded`:

```javascript
  const helpButton = document.getElementById("help-button");
  const helpPopover = document.getElementById("help-popover");
  if (helpButton && helpPopover && typeof helpPopover.showModal === "function") {
    helpButton.addEventListener("click", () => {
      if (helpPopover.open) helpPopover.close();
      else helpPopover.showModal();
    });
    helpPopover.addEventListener("click", (e) => {
      // click on backdrop closes
      if (e.target === helpPopover) helpPopover.close();
    });
  }
```

The reset button selector in the existing reset handler is unchanged (`#reset-session`); confirm the handler still fires after the markup move.

- [ ] **Step 6: Add CSS for popover**

Append to `web/static/css/chat.css`:

```css
/* ===== Help popover ===== */

.popover {
  border: 1px solid var(--surface-4);
  border-radius: var(--radius-lg);
  background: var(--surface-1);
  color: var(--text-1);
  padding: var(--space-4);
  max-width: 320px;
  box-shadow: var(--shadow-md);
}
.popover::backdrop { background: rgba(0,0,0,0.35); }
.popover__title  { margin: 0 0 var(--space-1); font-size: var(--text-md); }
.popover__meta   { margin: 0; color: var(--text-3); font-size: var(--text-xs); }
.popover__desc   { margin: var(--space-2) 0; color: var(--text-2); font-size: var(--text-sm); }
.popover__divider {
  border: 0;
  border-top: 1px solid var(--surface-4);
  margin: var(--space-2) 0;
}
.popover__link {
  background: transparent;
  border: 0;
  color: var(--accent-1);
  font: inherit;
  cursor: pointer;
  padding: var(--space-1) 0;
}
.popover__link:hover { color: var(--accent-1-hover); }
```

- [ ] **Step 7: Run the test**

```powershell
pytest tests/web/test_pages.py::test_chat_page_includes_app_version -v
```

Expected: PASS.

- [ ] **Step 8: Manual smoke**

Reload `/`. Click the `?` button → popover opens with title, version line, description, and a "Bắt đầu lại" link. Click the link → session resets. Click the backdrop → popover closes.

- [ ] **Step 9: Commit**

```powershell
git add web/routes/pages.py web/templates/chat.html web/static/css/chat.css web/static/js/chat.js tests/web/test_pages.py
git commit -m "$(cat <<'EOF'
feat(web): help popover with app version and reset link

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Update page tests + e2e; run full suite

**Files:**
- Modify: `tests/web/test_pages.py`
- Modify: `tests/web/test_chat_page.py`
- Modify (if needed): `tests/e2e/test_chat_web_flow.py`

- [ ] **Step 1: Extend `test_pages.py` for toast stack and greeting**

Append to `tests/web/test_pages.py`:

```python
def test_chat_page_renders_toast_stack():
    from fastapi.testclient import TestClient
    from web.app import build_app

    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="toast-stack"' in response.text


def test_chat_page_includes_greeting_empty_state_strings():
    """Greeting markup is rendered by JS; confirm the Vietnamese string lives
    in the bundled module so it ships with the page."""
    from pathlib import Path
    messages_js = Path("web/static/js/modules/messages.js").read_text(encoding="utf-8")
    assert "Xin chào! Hãy mô tả" in messages_js
```

- [ ] **Step 2: Extend `test_chat_page.py`**

Append to `tests/web/test_chat_page.py` (or add new assertions to an existing test that fetches `/`):

```python
def test_chat_page_has_help_popover_and_reset_inside():
    from fastapi.testclient import TestClient
    from web.app import build_app

    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert 'id="help-button"' in body
    assert 'id="help-popover"' in body
    assert 'id="reset-session"' in body
    # reset-session must live inside the popover, not in the header
    popover_idx = body.index('id="help-popover"')
    reset_idx = body.index('id="reset-session"')
    assert reset_idx > popover_idx, "reset-session must be rendered inside help-popover"
```

- [ ] **Step 3: Run web tests and fix selectors as needed**

```powershell
pytest tests/web -v
```

If any assertion fails on outdated class names (e.g. old `.chat-shell` 2-column markup), update the assertion to match the new IDs/classes from slice 02 (`#chat-panel`, `#profile-panel`, `#trace-panel`, `#composer-input`, etc.). Do NOT weaken the assertion — replace the selector with its slice-02 successor.

- [ ] **Step 4: Inspect and update e2e if it queries old selectors**

```powershell
Get-Content tests/e2e/test_chat_web_flow.py
```

If the test references the old structure (e.g. `find(".chat-shell")` expecting 2 columns, or a header-level `#reset-session`), update to the new selectors. Run:

```powershell
pytest tests/e2e/test_chat_web_flow.py -v
```

Expected: PASS.

- [ ] **Step 5: Run full non-integration suite**

```powershell
pytest -m "not integration" -v
```

Expected: 100 % pass. Capture the final summary line (e.g. `=== 142 passed in 8.3s ===`) and record it in the commit message.

- [ ] **Step 6: Commit**

```powershell
git add tests/web/test_pages.py tests/web/test_chat_page.py tests/e2e/test_chat_web_flow.py
git commit -m "$(cat <<'EOF'
test(web): cover toast stack, greeting strings, help popover, and reset placement

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Rewrite QUICKSTART.md UI section + add manual smoke checklist

**Files:**
- Modify: `QUICKSTART.md`

- [ ] **Step 1: Rewrite the existing trace-viewer section**

In `QUICKSTART.md`, find the section `### Optional: enable the trace viewer (dev-only)` (currently under section 5). Replace it with:

```markdown
### Optional: enable the trace viewer (dev-only)

Set the env flag before starting uvicorn:

```powershell
$env:ADVISORY_DEBUG_UI="1"
uvicorn web.app:build_app --factory --reload --port 8000
```

Then open `http://127.0.0.1:8000/?debug=1`. The right-hand "Phân tích của AI" panel
shows one card per agent stage with a Vietnamese label and an inline SVG icon
(`Phân tích hồ sơ`, `Tra cứu chương trình`, `Đối chiếu nguồn dữ liệu`, ...).
In debug mode each card becomes clickable and expands to pretty-printed
`output_json` for that stage. Without the env flag or query param the panel
remains visible during a run but cards are non-interactive.
```

- [ ] **Step 2: Insert a new "## 7. UI features" section after section 6**

In `QUICKSTART.md`, immediately after section `## 6. Demo flow` ends and before any troubleshooting section, insert:

```markdown
## 7. UI features

- **Theme toggle** — click `🌙` in the header to switch dark / light; preference
  persists per browser via `localStorage`. The page also honours
  `prefers-color-scheme` on first visit, and the server-side default can be
  overridden with `ADVISORY_THEME_DEFAULT=light|dark`.
- **Column collapse** — chevron handles (`◀` / `▶`) at the inner edge of each
  side panel collapse the column to a 32px gutter; click again to expand.
  Collapse state persists per browser.
- **Mobile drawer** — under 900px the side panels become overlays. Tap the
  hamburger icons in the header to open; press `Escape` or tap the backdrop
  to close.
- **Help popover** — the `?` icon opens a popover with the app version
  (read from `pyproject.toml`) and a `Bắt đầu lại` link that resets the session.
- **Markdown** — assistant final recommendations are rendered as markdown
  (bold school names, bullet lists). Loaded via `marked.js` from CDN with SRI.

### Manual smoke checklist

After any UI change run this checklist locally:

```text
1. Light → click 🌙 → dark applied immediately, reload → still dark.
2. Toggle left/right column collapse → reload → state persisted.
3. Send "Em muốn học CNTT" → user bubble right, AI follow-up bubble left.
4. Complete profile, trigger run → trace cards flip pending → running
   (spinner) → completed (duration), Vietnamese labels visible.
5. Visit /?debug=1 → trace cards become clickable, expand to show output_json.
6. Final recommendation: bold school names + bullet list render correctly
   (markdown).
7. Resize browser < 900px → side panels become drawers, header gains
   drawer-open icons.
8. Disconnect network mid-run → toast appears, polling auto-retries with backoff.
```
```

Renumber any section that previously followed (e.g. `## Troubleshooting` stays as-is — no number).

- [ ] **Step 3: Manual review**

```powershell
Get-Content QUICKSTART.md
```

Skim to confirm headings flow `1 → 2 → 3 → 4 → 5 → 6 → 7 → Troubleshooting`, the trace viewer paragraph reads correctly, and the smoke checklist is verbatim from spec §12.

- [ ] **Step 4: Commit**

```powershell
git add QUICKSTART.md
git commit -m "$(cat <<'EOF'
docs(quickstart): document Mastra-style UI features and manual smoke checklist

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Final smoke run end-to-end

**Files:** none (manual)

- [ ] **Step 1: Bring up full stack**

```powershell
docker compose up -d --wait db
$env:GEMINI_API_KEY="<your key>"
$env:ADVISORY_DEBUG_UI="1"
uvicorn web.app:build_app --factory --reload --port 8000
```

- [ ] **Step 2: Walk through the 8-item checklist from spec §12**

Open `http://127.0.0.1:8000/` (and `/?debug=1` for steps 5+) and execute each item in order. For each item, confirm the expected behavior:

  1. Light → `🌙` → dark; reload → still dark.
  2. Collapse left and right columns; reload → state persisted.
  3. Send `Em muốn học CNTT` → user bubble right, AI follow-up bubble left.
  4. Complete profile, trigger run → trace cards transition pending → running (spinner) → completed (duration) with Vietnamese labels.
  5. `/?debug=1` → click any completed card → output JSON expands.
  6. Final recommendation renders bolds and bullets (markdown).
  7. Resize to ~ 800 px wide → side panels become drawers; header shows drawer-open icons; `Escape` closes.
  8. DevTools → Network → Offline for 2 s during a run → warning toast appears; restore Online → polling resumes silently.

If any item fails, return to the relevant earlier task and fix, then re-run the full checklist before proceeding.

- [ ] **Step 3: Final non-integration test run for the record**

```powershell
pytest -m "not integration" -v
```

Expected: 100 % pass.

- [ ] **Step 4: Optionally run integration tests**

```powershell
pytest -m integration -v
```

Expected: 100 % pass (DB must be up).

- [ ] **Step 5: No commit — this task is verification only**

If all 8 checklist items and the test suite pass, the slice is complete.

---

## Slice 05 Done When

- [ ] Greeting card renders in an empty transcript with icon + welcome text + 3 clickable example chips; clicking a chip fills the composer and focuses it.
- [ ] Profile card shows `Hồ sơ sẽ tự cập nhật khi em trò chuyện.` when empty; recommendation card shows `Chưa có khuyến nghị.` when no result and not running.
- [ ] Recommendation card shows a 3-line pulsing skeleton while a run is in flight.
- [ ] `#chat-status[data-tone="pending"]` shows animated trailing dots.
- [ ] Toast module (`web/static/js/modules/toasts.js`) is in place; `#toast-stack` exists in `chat.html`; max 3 stacked; info/warning auto-dismiss 4 s, error 8 s with × button.
- [ ] `chat.js` triggers toasts on `schedulePolling` failure, `createSession` failure, and stale-token recovery; `trace.js` triggers a debounced (10 s) warning toast on trace-fetch failure.
- [ ] Mobile drawer (< 900 px) has a fading backdrop, slide-in animation, `Escape` closes, focus returns to the opener button, and `body` scroll is locked while open.
- [ ] Help popover opens from the header `?` button, displays app version read from `pyproject.toml` (falls back to `"dev"`), and contains the `#reset-session` button.
- [ ] All existing `tests/web/*` and `tests/e2e/test_chat_web_flow.py` pass; new assertions for `#toast-stack`, greeting strings, `#help-popover`, `#help-button`, and `app_version` are added and passing.
- [ ] `pytest -m "not integration"` reports 100 % pass; final summary captured in the commit message of Task 9.
- [ ] `QUICKSTART.md` has the rewritten trace-viewer section, a new `## 7. UI features` section, and the 8-item manual smoke checklist verbatim from spec §12.
- [ ] Manual smoke checklist (Task 11) executes top-to-bottom with no failures against a live Gemini-backed run.
- [ ] No new Python dependencies introduced; the only runtime additions are the new `toasts.js` ES module and the CSS / template tweaks listed above.

This is the final slice of the Mastra-style chat UI feature. Once Slice 05 is done, the feature is complete and ready for review.
