# Slice 03 — Messages & Markdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the inline transcript rendering out of `chat.js` into two new ES modules (`markdown.js` + `messages.js`), render assistant_result bubbles as sanitized markdown, restyle bubbles per the Mastra design (user-right / assistant-left / result-full-width / error-red), and polish the composer with auto-grow + Ctrl/Cmd+Enter submit + disabled-state logic.

**Architecture:** `markdown.js` wraps `window.marked` (loaded by slice 1 in `base.html`) and runs a DOM-based sanitizer (`DOMParser` → strip `<script>`/`<style>`/`on*=`/javascript URLs → enforce `target="_blank"` + `rel="noopener nofollow"` on links). `messages.js` owns all bubble construction: `renderTranscript`, `appendMessage`, and `renderRecommendationCard` (used by the left profile panel). `chat.js` shrinks to an orchestrator that imports these modules and wires composer events. Bubble styles live in `chat.css`; prose styles for rendered markdown live in a new `chat-markdown.css` loaded after `chat.css`.

**Tech Stack:** Jinja2, vanilla JS ES modules, plain CSS with design tokens, `marked.js` (already on `window`), pytest + FastAPI TestClient for HTML-level assertions.

---

### Task 1: Create `markdown.js` module

**Files:**
- Create: `web/static/js/modules/markdown.js`

- [ ] **Step 1: Write the module**

Create `web/static/js/modules/markdown.js`:

```javascript
// modules/markdown.js
// Wraps window.marked with a defense-in-depth sanitizer. Content is trusted
// (server-generated) but we still strip script/style/on*/javascript: URLs and
// force safe link attributes.

const JS_URL_RE = /^\s*javascript:/i;

function sanitize(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");

  doc.querySelectorAll("script, style").forEach((el) => el.remove());

  doc.querySelectorAll("*").forEach((el) => {
    // Strip on*= event handlers and any javascript: URLs.
    [...el.attributes].forEach((attr) => {
      const name = attr.name.toLowerCase();
      const value = attr.value || "";
      if (name.startsWith("on")) {
        el.removeAttribute(attr.name);
        return;
      }
      if ((name === "href" || name === "src") && JS_URL_RE.test(value)) {
        el.removeAttribute(attr.name);
      }
    });
  });

  doc.querySelectorAll("a").forEach((a) => {
    a.setAttribute("target", "_blank");
    a.setAttribute("rel", "noopener nofollow");
  });

  return doc.body.innerHTML;
}

export function renderMarkdown(src) {
  if (src == null) return "";
  if (typeof window === "undefined" || !window.marked) {
    // Fallback: escape and preserve newlines so the user still sees something.
    const div = document.createElement("div");
    div.textContent = String(src);
    return div.innerHTML.replace(/\n/g, "<br>");
  }
  const raw = window.marked.parse(String(src), { breaks: true, gfm: true });
  return sanitize(raw);
}
```

- [ ] **Step 2: Manual smoke (browser console)**

Bring up the server (no run needed):
```powershell
uvicorn web.app:build_app --factory --reload --port 8000
```

Open `http://127.0.0.1:8000/`, open devtools console, then paste:
```javascript
const m = await import("/static/js/modules/markdown.js");
console.log(m.renderMarkdown("# Hi\n\n- **bold**\n- [x](javascript:alert(1))\n- <script>alert(1)</script>"));
```

Expected: output contains `<h1>Hi</h1>` and `<strong>bold</strong>`; the `<script>` tag is gone; the `<a>` for `[x]` has no `href` (javascript: stripped) and has `target="_blank" rel="noopener nofollow"`.

- [ ] **Step 3: Commit**

```powershell
git add web/static/js/modules/markdown.js
git commit -m @'
feat(ui): add markdown.js module with sanitized marked wrapper

Wraps window.marked with a DOMParser-based sanitizer that strips
script/style tags, on*= event handlers, and javascript: URLs, then
enforces target=_blank / rel=noopener nofollow on links.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 2: Create `messages.js` module

**Files:**
- Create: `web/static/js/modules/messages.js`

- [ ] **Step 1: Write the module**

Create `web/static/js/modules/messages.js`:

```javascript
// modules/messages.js
// Owns all chat-bubble construction and the left-panel recommendation card.

import { renderMarkdown } from "./markdown.js";

function formatTimestamp(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return { iso, label: `${hh}:${mm}` };
}

function timestampNode(message) {
  const ts = formatTimestamp(message.created_at);
  if (!ts) return null;
  const time = document.createElement("time");
  time.className = "message__timestamp";
  time.setAttribute("datetime", ts.iso);
  time.textContent = ts.label;
  return time;
}

function _messageEl(message) {
  const article = document.createElement("article");
  const role = message.role || "assistant";
  const kind = message.kind || "text";
  article.className = `message message--${role} message--${kind}`;
  article.dataset.kind = kind;
  article.dataset.role = role;

  const bubble = document.createElement("div");
  bubble.className = "message__bubble";

  if (kind === "assistant_result") {
    bubble.classList.add("message__bubble--full", "message__bubble--markdown");
    bubble.innerHTML = renderMarkdown(message.content || "");
  } else if (kind === "assistant_error") {
    bubble.textContent = message.content || "";
    const cta = document.createElement("p");
    cta.className = "message__cta";
    cta.textContent = "Bấm 'Bắt đầu lại' để thử lại";
    bubble.appendChild(cta);
  } else {
    bubble.textContent = message.content || "";
  }

  article.appendChild(bubble);

  const ts = timestampNode(message);
  if (ts) article.appendChild(ts);

  return article;
}

export function renderTranscript(node, messages) {
  if (!node) return;
  node.innerHTML = "";
  (messages || []).forEach((message) => {
    node.appendChild(_messageEl(message));
  });
}

export function appendMessage(node, message) {
  if (!node || !message) return;
  node.appendChild(_messageEl(message));
}

export function renderRecommendationCard(node, content) {
  if (!node) return;
  if (!content) {
    node.textContent = "Chưa có khuyến nghị.";
    node.classList.remove("recommendation--has-content");
    return;
  }
  node.classList.add("recommendation--has-content");
  node.innerHTML = `<div class="message__bubble message__bubble--markdown">${renderMarkdown(content)}</div>`;
}
```

- [ ] **Step 2: Manual smoke (browser console)**

In the running dev server, open devtools console on `/` and paste:
```javascript
const m = await import("/static/js/modules/messages.js");
const node = document.getElementById("chat-transcript");
m.renderTranscript(node, [
  { role: "user", kind: "user_text", content: "Em muốn học CNTT", created_at: new Date().toISOString() },
  { role: "assistant", kind: "assistant_question", content: "Em dự kiến bao nhiêu điểm?", created_at: new Date().toISOString() },
  { role: "assistant", kind: "assistant_result", content: "# Khuyến nghị\n\n- **ĐH Bách Khoa HN**\n- ĐH Công nghệ", created_at: new Date().toISOString() },
]);
```

Expected: three `<article class="message ...">` nodes appear. The result bubble contains a real `<h1>` and `<ul>` (not raw markdown text). Each bubble carries a `<time>` timestamp child.

- [ ] **Step 3: Commit**

```powershell
git add web/static/js/modules/messages.js
git commit -m @'
feat(ui): add messages.js with bubble templates and recommendation renderer

Exports renderTranscript, appendMessage, and renderRecommendationCard.
Bubble class is message--<role> message--<kind>; assistant_result uses
the markdown renderer and a full-width bubble modifier; assistant_error
appends a "Bấm Bắt đầu lại để thử lại" CTA.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 3: Create `chat-markdown.css` prose styles

**Files:**
- Create: `web/static/css/chat-markdown.css`

- [ ] **Step 1: Write the stylesheet**

Create `web/static/css/chat-markdown.css`:

```css
/* chat-markdown.css
 * Prose styles scoped to .message__bubble.message__bubble--markdown.
 * Loaded AFTER chat.css so design tokens are already defined.
 */

.message__bubble--markdown {
  line-height: var(--leading-base, 1.55);
  font-size: var(--text-base, 14px);
  color: var(--text-1);
}

.message__bubble--markdown > *:first-child { margin-top: 0; }
.message__bubble--markdown > *:last-child  { margin-bottom: 0; }

.message__bubble--markdown h1,
.message__bubble--markdown h2,
.message__bubble--markdown h3,
.message__bubble--markdown h4 {
  color: var(--text-1);
  font-weight: 600;
  line-height: var(--leading-tight, 1.3);
  margin: var(--space-4, 16px) 0 var(--space-2, 8px);
}

.message__bubble--markdown h1 { font-size: var(--text-xl, 20px); }
.message__bubble--markdown h2 { font-size: var(--text-lg, 17px); }
.message__bubble--markdown h3 { font-size: var(--text-md, 15px); }
.message__bubble--markdown h4 { font-size: var(--text-base, 14px); text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-2); }

.message__bubble--markdown p {
  margin: 0 0 var(--space-3, 12px);
}

.message__bubble--markdown ul,
.message__bubble--markdown ol {
  margin: 0 0 var(--space-3, 12px);
  padding-left: var(--space-5, 24px);
}

.message__bubble--markdown li {
  margin-bottom: var(--space-1, 4px);
}

.message__bubble--markdown strong { font-weight: 600; color: var(--text-1); }
.message__bubble--markdown em     { font-style: italic; }

.message__bubble--markdown code {
  font-family: var(--font-mono);
  font-size: 0.92em;
  background: var(--surface-3);
  padding: 1px 4px;
  border-radius: var(--radius-sm, 4px);
}

.message__bubble--markdown pre {
  margin: 0 0 var(--space-3, 12px);
  padding: var(--space-3, 12px);
  background: var(--surface-3);
  border-radius: var(--radius-md, 6px);
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: var(--text-sm, 13px);
  line-height: var(--leading-base, 1.55);
}

.message__bubble--markdown pre code {
  background: transparent;
  padding: 0;
  border-radius: 0;
  font-size: inherit;
}

.message__bubble--markdown a {
  color: var(--accent-1);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.message__bubble--markdown a:hover {
  color: var(--accent-1-hover);
}

.message__bubble--markdown blockquote {
  margin: 0 0 var(--space-3, 12px);
  padding: var(--space-1, 4px) var(--space-3, 12px);
  border-left: 3px solid var(--surface-4);
  color: var(--text-2);
}

.message__bubble--markdown table {
  width: 100%;
  border-collapse: collapse;
  margin: 0 0 var(--space-3, 12px);
  font-size: var(--text-sm, 13px);
}

.message__bubble--markdown th,
.message__bubble--markdown td {
  padding: var(--space-2, 8px) var(--space-3, 12px);
  border-bottom: 1px solid var(--surface-4);
  text-align: left;
}

.message__bubble--markdown th {
  font-weight: 600;
  background: var(--surface-3);
}

.message__bubble--markdown tbody tr:nth-child(even) td {
  background: var(--surface-2);
}

.message__bubble--markdown hr {
  border: 0;
  border-top: 1px solid var(--surface-4);
  margin: var(--space-4, 16px) 0;
}
```

- [ ] **Step 2: Commit**

```powershell
git add web/static/css/chat-markdown.css
git commit -m @'
feat(ui): add chat-markdown.css prose styles for rendered bubbles

Scoped to .message__bubble--markdown so it cannot bleed into plain
bubbles. Headings, lists, code, pre, links, blockquotes, and striped
tables all consume design tokens from tokens.css.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 4: Load `chat-markdown.css` in `base.html`

**Files:**
- Modify: `web/templates/base.html`

- [ ] **Step 1: Add the link tag after `chat.css`**

In `web/templates/base.html`, find:
```html
    <link rel="stylesheet" href="/static/css/chat.css" />
```

Add immediately after it:
```html
    <link rel="stylesheet" href="/static/css/chat-markdown.css" />
```

- [ ] **Step 2: Manual check**

Reload `http://127.0.0.1:8000/` and confirm in the Network panel that `chat-markdown.css` returns 200. In Elements, hover the `<link>` and confirm it loads after `chat.css`.

- [ ] **Step 3: Commit**

```powershell
git add web/templates/base.html
git commit -m @'
feat(ui): load chat-markdown.css after chat.css in base layout

Cascade order matters: markdown prose styles must come after base
chat styles so token-based overrides win.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 5: Replace old `.message` styles in `chat.css` with new bubble anatomy

**Files:**
- Modify: `web/static/css/chat.css`

- [ ] **Step 1: Remove the legacy `.message`, `.message--user`, `.message--assistant` rules**

Open `web/static/css/chat.css` and delete the existing `.message`, `.message--user`, and `.message--assistant` rule blocks (the ones that pre-date this slice — they style a single flat bubble without the new BEM structure).

- [ ] **Step 2: Append the new bubble anatomy**

Append the following to `web/static/css/chat.css`:

```css
/* ===== Message bubbles (slice 03) ===== */

.message {
  display: flex;
  flex-direction: column;
  gap: var(--space-1, 4px);
  max-width: 100%;
}

.message--user {
  align-items: flex-end;
}

.message--assistant {
  align-items: flex-start;
}

.message__bubble {
  max-width: var(--bubble-max, 70%);
  padding: var(--space-3, 12px) var(--space-4, 16px);
  border-radius: 10px;
  background: var(--assistant-bg);
  color: var(--text-1);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  box-shadow: var(--shadow-sm);
}

.message--user .message__bubble {
  background: var(--user-bubble);
  border-radius: 10px 10px 2px 10px;
}

.message--assistant .message__bubble {
  background: var(--assistant-bg);
  border-radius: 10px 10px 10px 2px;
}

.message__bubble--full {
  max-width: 100%;
  width: 100%;
  padding: var(--space-4, 16px) var(--space-5, 24px);
  white-space: normal;  /* markdown handles its own whitespace */
}

.message__bubble--markdown {
  white-space: normal;
}

.message__timestamp {
  font-size: var(--text-xs, 12px);
  color: var(--text-3);
  padding: 0 var(--space-2, 8px);
  font-variant-numeric: tabular-nums;
}

.message--assistant_error .message__bubble {
  background: color-mix(in oklch, var(--negative) 12%, var(--surface-2));
  border: 1px solid color-mix(in oklch, var(--negative) 35%, transparent);
  color: var(--text-1);
}

.message__cta {
  margin: var(--space-3, 12px) 0 0;
  font-size: var(--text-sm, 13px);
  color: var(--negative);
  font-weight: 600;
}

/* ===== Composer (slice 03 polish) ===== */

#chat-input {
  width: 100%;
  min-height: 56px;
  max-height: 240px;
  resize: none;
  padding: var(--space-3, 12px) var(--space-4, 16px);
  font-family: var(--font-sans);
  font-size: var(--text-md, 15px);
  line-height: var(--leading-base, 1.55);
  background: var(--surface-2);
  color: var(--text-1);
  border: 1px solid var(--surface-4);
  border-radius: var(--radius-md, 6px);
  overflow-y: auto;
  transition: border-color var(--transition-fast, 120ms ease);
}

#chat-input:focus {
  outline: none;
  border-color: var(--accent-1);
}

.chat-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3, 12px);
  margin-top: var(--space-2, 8px);
}

.composer-hint {
  flex: 0 0 auto;
  font-size: var(--text-xs, 12px);
  color: var(--text-3);
}

.composer-status {
  flex: 1 1 auto;
  text-align: center;
  font-size: var(--text-sm, 13px);
  color: var(--text-2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2, 8px);
}

.composer-status[data-tone="pending"]::before {
  content: "";
  width: 12px;
  height: 12px;
  border: 2px solid var(--surface-4);
  border-top-color: var(--accent-1);
  border-radius: 50%;
  animation: composer-spin 0.8s linear infinite;
}

@keyframes composer-spin {
  to { transform: rotate(360deg); }
}

#send-button {
  flex: 0 0 auto;
  padding: var(--space-2, 8px) var(--space-5, 24px);
  font-size: var(--text-base, 14px);
  font-weight: 600;
  background: var(--accent-1);
  color: var(--accent-1-contrast);
  border: 0;
  border-radius: var(--radius-md, 6px);
  cursor: pointer;
  transition: background var(--transition-fast, 120ms ease);
}

#send-button:hover:not(:disabled) { background: var(--accent-1-hover); }
#send-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

- [ ] **Step 3: Manual visual check**

Reload `/`. With Task 2's console snippet still in mind, paste it again:
```javascript
const m = await import("/static/js/modules/messages.js");
m.renderTranscript(document.getElementById("chat-transcript"), [
  { role: "user", kind: "user_text", content: "Em muốn học CNTT", created_at: new Date().toISOString() },
  { role: "assistant", kind: "assistant_question", content: "Em dự kiến bao nhiêu điểm?", created_at: new Date().toISOString() },
  { role: "assistant", kind: "assistant_result", content: "# Khuyến nghị\n\n- **ĐH Bách Khoa HN**\n- ĐH Công nghệ", created_at: new Date().toISOString() },
  { role: "assistant", kind: "assistant_error", content: "Mạng tạm thời gián đoạn." },
]);
```

Expected:
- User bubble aligns right, max ~70% width, soft green-tinted background, sharp bottom-right corner.
- Assistant question bubble aligns left, neutral surface, sharp bottom-left corner.
- Assistant result spans the full width of the transcript, renders markdown with `<h1>` + `<ul>`.
- Error bubble has a red-tinted background, a red border, and a "Bấm 'Bắt đầu lại' để thử lại" line.

- [ ] **Step 4: Commit**

```powershell
git add web/static/css/chat.css
git commit -m @'
feat(ui): rebuild message bubble styles per Mastra design

User bubbles align right with 70% max-width and asymmetric radius;
assistant questions align left with mirrored radius; assistant_result
uses message__bubble--full for full-width markdown rendering;
assistant_error uses a negative-tinted bubble with a CTA paragraph.
Also restyles the composer textarea and the chat-actions row.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 6: Wire `chat.js` to import and use the new modules

**Files:**
- Modify: `web/static/js/chat.js`

- [ ] **Step 1: Add imports at the top**

In `web/static/js/chat.js`, immediately above `const SESSION_KEY = "student-advisory-session-token";`, add:

```javascript
import { renderTranscript, appendMessage, renderRecommendationCard } from "./modules/messages.js";
```

(`appendMessage` is imported now even if not used today, so optimistic UI can be wired in slice 05 without another import edit.)

- [ ] **Step 2: Remove the old inline `renderTranscript` function**

Delete this block (currently lines ~128–139):
```javascript
function renderTranscript(messages) {
  const node = document.getElementById("chat-transcript");
  if (!node) return;
  node.innerHTML = "";
  messages.forEach((message) => {
    const item = document.createElement("article");
    item.className = `message message--${message.role}`;
    item.dataset.kind = message.kind;
    item.textContent = message.content;
    node.appendChild(item);
  });
}
```

- [ ] **Step 3: Replace the inline `renderRecommendation` to delegate to the module**

Find:
```javascript
function renderRecommendation(snapshot) {
  const node = document.getElementById("recommendation-panel");
  if (!node) return;
  const latest = getLatestRecommendation(snapshot.messages || []);
  node.textContent = latest ? latest.content : "Chưa có khuyến nghị.";
}
```

Replace with:
```javascript
function renderRecommendation(snapshot) {
  const node = document.getElementById("recommendation-panel");
  if (!node) return;
  const latest = getLatestRecommendation(snapshot.messages || []);
  renderRecommendationCard(node, latest ? latest.content : null);
}
```

- [ ] **Step 4: Update `renderSnapshot` to pass the transcript node into the module**

Find:
```javascript
function renderSnapshot(snapshot) {
  renderTranscript(snapshot.messages || []);
  renderProfileSummary(snapshot);
  renderRecommendation(snapshot);
}
```

Replace with:
```javascript
function renderSnapshot(snapshot) {
  const transcript = document.getElementById("chat-transcript");
  renderTranscript(transcript, snapshot.messages || []);
  renderProfileSummary(snapshot);
  renderRecommendation(snapshot);
}
```

- [ ] **Step 5: Manual smoke**

Reload `/` and start a chat. Expected:
- Transcript renders bubbles via the new module (verify in Elements: each `<article>` now has a child `<div class="message__bubble">`, not flat text).
- "Khuyến nghị mới nhất" panel renders markdown bullets / headings instead of raw text, once a recommendation arrives.

- [ ] **Step 6: Commit**

```powershell
git add web/static/js/chat.js
git commit -m @'
refactor(ui): delegate transcript and recommendation rendering to modules

chat.js now imports renderTranscript, appendMessage, and
renderRecommendationCard from ./modules/messages.js, drops the
inline renderTranscript function, and routes the left-panel
recommendation card through the markdown-rendering helper.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 7: Composer auto-grow + Ctrl/Cmd+Enter + send-disabled logic

**Files:**
- Modify: `web/static/js/chat.js`

- [ ] **Step 1: Add helpers near the top of `chat.js`**

After the `import` line added in Task 6, add:

```javascript
const COMPOSER_MAX_PX = 240;

function autoGrow(textarea) {
  if (!textarea) return;
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, COMPOSER_MAX_PX) + "px";
}

function syncSendDisabled(input, button, statusEl) {
  if (!input || !button) return;
  const empty = input.value.trim().length === 0;
  const pending = statusEl?.dataset.tone === "pending";
  button.disabled = empty || pending;
}
```

- [ ] **Step 2: Wire composer event handlers inside `DOMContentLoaded`**

Inside the `DOMContentLoaded` callback, right after the existing line:
```javascript
  const resetButton = document.getElementById("reset-session");
```
add:

```javascript
  const sendButton = document.getElementById("send-button");
  const statusEl = document.getElementById("chat-status");

  input.addEventListener("input", () => {
    autoGrow(input);
    syncSendDisabled(input, sendButton, statusEl);
  });

  input.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      if (!sendButton.disabled) form.requestSubmit();
    }
  });

  // Keep send-disabled in sync whenever status tone changes.
  const statusObserver = new MutationObserver(() =>
    syncSendDisabled(input, sendButton, statusEl)
  );
  if (statusEl) {
    statusObserver.observe(statusEl, { attributes: true, attributeFilter: ["data-tone"] });
  }

  // Initial state.
  autoGrow(input);
  syncSendDisabled(input, sendButton, statusEl);
```

- [ ] **Step 3: Clear textarea height after successful send**

Inside the existing form submit handler, find:
```javascript
      input.value = "";
```
Replace with:
```javascript
      input.value = "";
      autoGrow(input);
      syncSendDisabled(input, sendButton, statusEl);
```

- [ ] **Step 4: Manual smoke**

Reload `/`. Verify:
- Typing in the textarea grows it line-by-line up to ~240px, then it scrolls internally.
- With the textarea empty, the Send button is disabled (greyed).
- Typing a character enables Send.
- Submitting (or status tone going to `pending`) re-disables Send.
- Ctrl+Enter (or Cmd+Enter on macOS) submits the form.
- Plain Enter inserts a newline (browser default — no preventDefault).

- [ ] **Step 5: Commit**

```powershell
git add web/static/js/chat.js
git commit -m @'
feat(ui): composer auto-grow, Ctrl/Cmd+Enter submit, send-disabled sync

Textarea grows on input up to 240px and scrolls beyond. Send button
disables when input is empty or status tone is pending (observed via
MutationObserver on data-tone). Ctrl/Cmd+Enter triggers requestSubmit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 8: Composer hint + status markup in `chat.html`

**Files:**
- Modify: `web/templates/chat.html`

- [ ] **Step 1: Update the `.chat-actions` row to include the hint and a centered status element**

In `web/templates/chat.html`, find:
```html
      <div class="chat-actions">
        <button id="send-button" type="submit">Gửi</button>
      </div>
```

Replace with:
```html
      <div class="chat-actions">
        <span class="composer-hint">Ctrl+Enter để gửi</span>
        <span id="composer-status" class="composer-status" aria-live="polite"></span>
        <button id="send-button" type="submit" disabled>Gửi</button>
      </div>
```

(The existing top-of-panel `#chat-status` stays — it announces page-level state. `#composer-status` is the inline pending-spinner area next to the Send button. For this slice, leaving `#composer-status` empty is fine; slice 05 will wire it.)

- [ ] **Step 2: Manual visual check**

Reload `/`. Expected: under the textarea, on one row: muted "Ctrl+Enter để gửi" on the left, empty status in the middle, disabled "Gửi" on the right.

- [ ] **Step 3: Commit**

```powershell
git add web/templates/chat.html
git commit -m @'
feat(ui): add composer hint and inline status slot to chat template

Bottom row now shows "Ctrl+Enter để gửi" hint on the left, an inline
composer-status slot in the middle (wired in a later slice), and the
Send button (initially disabled) on the right.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 9: Tests — composer hint + markdown stylesheet link + template render

**Files:**
- Modify: `tests/web/test_chat_page.py`
- Create: `tests/web/test_chat_template_render.py`

- [ ] **Step 1: Extend `test_chat_page.py` with a composer-hint assertion**

Open `tests/web/test_chat_page.py` and add (as a new test function at the end, copying the existing import + client-fixture style):

```python
def test_chat_page_shows_composer_hint():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "Ctrl+Enter để gửi" in response.text
```

If `TestClient` / `build_app` are not already imported in that file, add:
```python
from fastapi.testclient import TestClient

from web.app import build_app
```

- [ ] **Step 2: Run to confirm pass**

```powershell
pytest tests/web/test_chat_page.py -v
```
Expected: PASS (Task 8 already added the hint string to the template).

- [ ] **Step 3: Create `test_chat_template_render.py`**

Create `tests/web/test_chat_template_render.py`:

```python
"""Static template assertions for the chat page.

These tests stay at the HTML-string level (no JS execution); they verify
the contract that slice-03 assets are linked and the composer slots exist.
"""

from fastapi.testclient import TestClient

from web.app import build_app


def test_chat_template_links_chat_markdown_css():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "/static/css/chat-markdown.css" in response.text


def test_chat_template_has_chat_input_textarea():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert '<textarea' in response.text
    assert 'id="chat-input"' in response.text


def test_chat_template_has_send_button_and_status_slot():
    client = TestClient(build_app())
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="send-button"' in response.text
    assert 'id="composer-status"' in response.text
```

- [ ] **Step 4: Run to confirm pass**

```powershell
pytest tests/web/test_chat_template_render.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Run the full web suite to confirm no regressions**

```powershell
pytest tests/web -v
```
Expected: all green.

- [ ] **Step 6: Commit**

```powershell
git add tests/web/test_chat_page.py tests/web/test_chat_template_render.py
git commit -m @'
test(web): assert composer hint and markdown stylesheet link render

test_chat_page now asserts the "Ctrl+Enter để gửi" hint string is
present. New test_chat_template_render covers the slice-03 contract:
chat-markdown.css link, chat-input textarea, send-button + composer
status slot.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
'@
```

---

### Task 10: Manual end-to-end smoke

**Files:** (no edits — verification only)

- [ ] **Step 1: Bring up the stack**

```powershell
docker compose up -d --wait db
$env:GEMINI_API_KEY="<your key>"
uvicorn web.app:build_app --factory --reload --port 8000
```

- [ ] **Step 2: Send a real run**

Open `http://127.0.0.1:8000/`, send: `Em muốn học CNTT ở Hà Nội năm 2026, dự kiến được 27 điểm.`

Expected during the run:
- User bubble aligns right with the new asymmetric radius.
- Follow-up assistant questions appear as left-aligned bubbles.
- The final `assistant_result` bubble spans the full transcript width and renders markdown: bold school names, bullet list, headings if present, no raw `#` or `*` characters.
- A timestamp `HH:mm` appears next to each bubble.
- The "Khuyến nghị mới nhất" card in the left panel mirrors the recommendation in markdown form.

- [ ] **Step 3: Sanitizer smoke**

In devtools console paste:
```javascript
const m = await import("/static/js/modules/messages.js");
m.appendMessage(
  document.getElementById("chat-transcript"),
  { role: "assistant", kind: "assistant_result", content: "Hello <script>window.__pwn=1</script> **world**", created_at: new Date().toISOString() }
);
console.log("pwn:", window.__pwn);
```

Expected: a new bubble appears containing the text "Hello" followed by bold "world"; no `<script>` element exists in the DOM (inspect the bubble); `window.__pwn` is `undefined`.

- [ ] **Step 4: Composer smoke**

- Type then erase → Send disables/enables correctly.
- Hold Shift+Enter → newline inserted; textarea grows.
- Type a long block (8+ lines) → textarea caps at ~240px and starts scrolling internally.
- Ctrl+Enter → submits the form.

- [ ] **Step 5: Final test run**

```powershell
pytest -m "not integration"
```
Expected: all green.

- [ ] **Step 6: No commit needed — verification only**

If anything failed above, fix in a follow-up task within this slice and re-run from Step 1.

---

## Slice 03 Done When

- [ ] `web/static/js/modules/markdown.js` exists and exports a sanitized `renderMarkdown`.
- [ ] `web/static/js/modules/messages.js` exists and exports `renderTranscript`, `appendMessage`, `renderRecommendationCard`.
- [ ] `web/static/css/chat-markdown.css` exists and is linked after `chat.css` in `base.html`.
- [ ] `web/static/css/chat.css` no longer contains the legacy `.message--user` / `.message--assistant` flat rules and now defines the new `.message__bubble` BEM anatomy plus composer styles.
- [ ] `web/static/js/chat.js` imports from `./modules/messages.js`, no longer defines `renderTranscript` inline, and delegates the recommendation card to `renderRecommendationCard`.
- [ ] Textarea auto-grows on input up to 240px; Ctrl/Cmd+Enter submits; Send button disables on empty input or `pending` status.
- [ ] `web/templates/chat.html` shows the "Ctrl+Enter để gửi" hint and the `#composer-status` slot.
- [ ] `pytest tests/web -v` is fully green; `pytest -m "not integration"` is green.
- [ ] Manual end-to-end run shows: user bubbles right, assistant questions left, assistant_result full-width markdown, sanitizer strips an injected `<script>` so no `window.__pwn` global appears.
- [ ] All 10 task commits are on the slice branch; no work in progress remaining.
