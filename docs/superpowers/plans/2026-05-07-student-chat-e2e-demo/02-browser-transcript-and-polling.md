# Student Chat E2E Demo - Plan 2: Browser Transcript And Polling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing public chat page into a snapshot-driven browser client that renders conversation state, profile state, and advisory-run progress.

**Architecture:** Keep the UI intentionally thin and server-state-driven. The page should bootstrap or restore a session, fetch snapshots from the backend, render transcript and profile summary from those snapshots, and poll when the server says a run has started.

**Tech Stack:** FastAPI, Jinja2, vanilla JavaScript, CSS, `pytest`, `fastapi.testclient`

---

## Planned File Structure

- `web/templates/chat.html`
  - Add status, transcript, and action hooks required by the browser client.
- `web/static/js/chat.js`
  - Replace the send-only script with snapshot rendering, profile summary rendering, and polling logic.
- `web/static/css/chat.css`
  - Add transcript, status, and summary styling for the demo state machine.
- `tests/web/test_chat_page.py`
  - Verify the page exposes the DOM hooks needed by the client.
- `tests/e2e/test_chat_web_flow.py`
  - Add static-client regression tests for snapshot and polling helpers.

### Task 1: Expand The Chat Page Markup For Live Session State

**Files:**
- Modify: `web/templates/chat.html`
- Modify: `web/static/css/chat.css`
- Modify: `tests/web/test_chat_page.py`

- [ ] **Step 1: Write the failing test**

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_chat_page.py::test_chat_page_renders_status_reset_and_results_regions -v`
Expected: FAIL because the current template only includes `chat-transcript`, `chat-input`, and `profile-summary`.

- [ ] **Step 3: Write minimal implementation**

```html
<!-- web/templates/chat.html -->
{% extends "base.html" %}
{% block body %}
<main class="chat-shell">
  <section class="chat-panel">
    <header class="chat-header">
      <h1>Student Advisory Chat</h1>
      <button id="reset-session" type="button" class="secondary-button">Bat dau lai</button>
    </header>

    <div id="chat-status" class="chat-status" aria-live="polite"></div>
    <div id="chat-transcript" class="chat-transcript" aria-live="polite"></div>

    <form id="chat-form" class="chat-form">
      <label for="chat-input" class="sr-only">Noi dung tin nhan</label>
      <textarea
        id="chat-input"
        name="content"
        rows="4"
        placeholder="Vi du: Em muon hoc CNTT o Ha Noi nam 2026, du kien duoc 27 diem."
      ></textarea>
      <div class="chat-actions">
        <button id="send-button" type="submit">Gui</button>
      </div>
    </form>
  </section>

  <aside class="summary-panel">
    <section>
      <h2>Ho so tam thoi</h2>
      <div id="profile-summary"></div>
    </section>
    <section>
      <h2>Khuyen nghi moi nhat</h2>
      <div id="recommendation-panel"></div>
    </section>
  </aside>
</main>
{% endblock %}
```

```css
/* web/static/css/chat.css */
body {
  margin: 0;
  font-family: "Segoe UI", sans-serif;
  background: linear-gradient(180deg, #f5f1e8 0%, #efe6d8 100%);
  color: #1f2933;
}

.chat-shell {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr);
  gap: 24px;
  min-height: 100vh;
  padding: 32px;
}

.chat-panel,
.summary-panel {
  background: rgba(255, 255, 255, 0.88);
  border-radius: 20px;
  padding: 24px;
  box-shadow: 0 18px 48px rgba(31, 41, 51, 0.08);
}

.chat-header,
.chat-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.chat-status {
  min-height: 24px;
  margin: 16px 0;
  font-size: 14px;
  color: #8a5b18;
}

.chat-transcript {
  display: grid;
  gap: 12px;
  min-height: 280px;
  margin-bottom: 16px;
}

.chat-form textarea {
  width: 100%;
  border: 1px solid #d5d9de;
  border-radius: 14px;
  padding: 14px;
  resize: vertical;
}

.secondary-button {
  border: 1px solid #c8cdd4;
  background: #fff;
  border-radius: 999px;
  padding: 10px 14px;
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/web/test_chat_page.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/templates/chat.html web/static/css/chat.css tests/web/test_chat_page.py
git commit -m "feat: add chat page hooks for live session state"
```

### Task 2: Replace The Send-Only Client With Snapshot Rendering And Polling

**Files:**
- Modify: `web/static/js/chat.js`
- Modify: `tests/e2e/test_chat_web_flow.py`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


def test_chat_client_supports_snapshot_refresh_and_run_polling():
    script = Path("web/static/js/chat.js").read_text(encoding="utf-8")

    assert "async function fetchSessionSnapshot" in script
    assert "function renderTranscript" in script
    assert "function renderProfileSummary" in script
    assert "function schedulePolling" in script
    assert "window.localStorage" in script
    assert "`/api/sessions/${sessionToken}`" in script
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/e2e/test_chat_web_flow.py::test_chat_client_supports_snapshot_refresh_and_run_polling -v`
Expected: FAIL because the current script only defines `ensureSession()` and `sendMessage()` and does not fetch snapshots or poll.

- [ ] **Step 3: Write minimal implementation**

```javascript
// web/static/js/chat.js
const SESSION_KEY = "student-advisory-session-token";
const POLL_INTERVAL_MS = 1200;

let pollTimer = null;
let currentSessionToken = null;

function setStatus(message, tone = "info") {
  const node = document.getElementById("chat-status");
  if (!node) return;
  node.textContent = message || "";
  node.dataset.tone = tone;
}

function getProfileState(snapshot) {
  return snapshot?.session?.profile_state_json || {};
}

function getLatestRecommendation(messages) {
  return [...messages].reverse().find((message) => message.kind === "assistant_result") || null;
}

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

function renderProfileSummary(snapshot) {
  const node = document.getElementById("profile-summary");
  if (!node) return;
  const profile = getProfileState(snapshot);
  const entries = [
    ["Nam tuyen sinh", profile.admission_year],
    ["Tong diem", profile.total_score],
    ["Nganh quan tam", (profile.preferred_majors || []).join(", ")],
    ["Khu vuc", profile.location_preference],
    ["Con thieu", (profile.missing_slots || []).join(", ")],
  ].filter(([, value]) => value);

  if (entries.length === 0) {
    node.textContent = "Chua co du lieu ho so.";
    return;
  }

  node.innerHTML = entries
    .map(([label, value]) => `<p><strong>${label}:</strong> ${value}</p>`)
    .join("");
}

function renderRecommendation(snapshot) {
  const node = document.getElementById("recommendation-panel");
  if (!node) return;
  const latest = getLatestRecommendation(snapshot.messages || []);
  node.textContent = latest ? latest.content : "Chua co khuyen nghi.";
}

function renderSnapshot(snapshot) {
  renderTranscript(snapshot.messages || []);
  renderProfileSummary(snapshot);
  renderRecommendation(snapshot);
}

async function createSession() {
  const response = await fetch("/api/sessions", { method: "POST" });
  if (!response.ok) {
    throw new Error("Khong the tao phien chat moi.");
  }
  const payload = await response.json();
  currentSessionToken = payload.session.session_token;
  window.localStorage.setItem(SESSION_KEY, currentSessionToken);
  return payload;
}

async function fetchSessionSnapshot(sessionToken) {
  const response = await fetch(`/api/sessions/${sessionToken}`);
  if (!response.ok) {
    throw new Error("Khong the tai lai lich su hoi thoai.");
  }
  return response.json();
}

async function ensureSession() {
  const stored = window.localStorage.getItem(SESSION_KEY);
  if (!stored) {
    return createSession();
  }
  currentSessionToken = stored;
  return fetchSessionSnapshot(stored);
}

function stopPolling() {
  if (pollTimer) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function schedulePolling(sessionToken) {
  stopPolling();
  pollTimer = window.setTimeout(async () => {
    const snapshot = await fetchSessionSnapshot(sessionToken);
    renderSnapshot(snapshot);
    if (snapshot.session.status === "completed") {
      setStatus("Da co ket qua tu van.", "success");
      stopPolling();
      return;
    }
    if (snapshot.session.status === "failed") {
      setStatus("Qua trinh phan tich bi gian doan.", "error");
      stopPolling();
      return;
    }
    schedulePolling(sessionToken);
  }, POLL_INTERVAL_MS);
}

async function sendMessage(content) {
  const sessionToken = currentSessionToken || window.localStorage.getItem(SESSION_KEY);
  const response = await fetch(`/api/sessions/${sessionToken}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!response.ok) {
    throw new Error("Khong gui duoc tin nhan.");
  }
  return response.json();
}

document.addEventListener("DOMContentLoaded", async () => {
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const resetButton = document.getElementById("reset-session");

  const bootstrap = await ensureSession();
  renderSnapshot(bootstrap);
  setStatus("San sang tu van.", "info");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (!content) return;

    setStatus("Dang gui tin nhan...", "pending");
    const result = await sendMessage(content);
    input.value = "";

    const snapshot = await fetchSessionSnapshot(currentSessionToken);
    renderSnapshot(snapshot);

    if (result.should_start_run) {
      setStatus("Dang phan tich ho so...", "pending");
      schedulePolling(currentSessionToken);
      return;
    }

    setStatus("Da nhan cau hoi tiep theo.", "info");
  });

  resetButton.addEventListener("click", async () => {
    stopPolling();
    window.localStorage.removeItem(SESSION_KEY);
    const snapshot = await createSession();
    renderSnapshot(snapshot);
    setStatus("Da bat dau phien chat moi.", "info");
  });
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/e2e/test_chat_web_flow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/static/js/chat.js tests/e2e/test_chat_web_flow.py
git commit -m "feat: render chat snapshots and poll advisory runs"
```

## Self-Review

Spec coverage in this plan:
- transcript rendering: covered by Task 1 and Task 2.
- profile summary panel: covered by Task 2.
- analyzing state and polling: covered by Task 2.

Placeholder scan:
- No unresolved placeholders remain.

Type consistency:
- The plan consistently uses `profile_state_json`, `messages`, `session.status`, and `assistant_result`.
