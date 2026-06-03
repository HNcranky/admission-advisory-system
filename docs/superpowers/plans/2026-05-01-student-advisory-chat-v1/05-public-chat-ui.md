# Student Advisory Chat V1 - Phase 5: Public Chat UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the first student/parent-facing web page on top of the completed anonymous session and advisory-run APIs.

**Architecture:** Keep the UI intentionally thin: server-render a single chat shell with Jinja2, then use a small vanilla JavaScript client to manage session bootstrap, transcript refresh, message sending, and polling while a background advisory run is active. This preserves the API-first backend from earlier phases while producing a usable public entrypoint.

**Tech Stack:** Python, FastAPI, Jinja2, vanilla JavaScript, CSS, `pytest`, `fastapi.testclient`

---

## Planned File Structure

- `web/routes/pages.py`
  - Serve the public chat page.
- `web/templates/base.html`
  - Shared page chrome for the student-facing UI.
- `web/templates/chat.html`
  - Chat transcript, profile summary, recommendation panel, and send form.
- `web/static/js/chat.js`
  - Session token persistence, message submission, and status polling.
- `web/static/css/chat.css`
  - First-pass visual styling for the public product.

### Task 1: Add The Public Chat Page Shell

**Files:**
- Modify: `web/app.py`
- Create: `web/routes/pages.py`
- Create: `web/templates/base.html`
- Create: `web/templates/chat.html`
- Test: `tests/web/test_chat_page.py`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from web.app import build_app


def test_chat_page_renders_shell():
    client = TestClient(build_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "Student Advisory Chat" in response.text
    assert 'id="chat-transcript"' in response.text
    assert 'id="profile-summary"' in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/web/test_chat_page.py -v`
Expected: FAIL with `404 Not Found` for `/`

- [ ] **Step 3: Write minimal implementation**

```python
# web/routes/pages.py
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates


router = APIRouter()
templates = Jinja2Templates(directory="web/templates")


@router.get("/")
def chat_page(request: Request):
    return templates.TemplateResponse(
        request,
        "chat.html",
        {"page_title": "Student Advisory Chat"},
    )
```

```python
# web/templates/base.html
<!DOCTYPE html>
<html lang="vi">
  <head>
    <meta charset="utf-8" />
    <title>{{ page_title }}</title>
    <link rel="stylesheet" href="/static/css/chat.css" />
  </head>
  <body>
    {% block body %}{% endblock %}
    <script src="/static/js/chat.js"></script>
  </body>
</html>
```

```html
<!-- web/templates/chat.html -->
{% extends "base.html" %}
{% block body %}
<main class="chat-shell">
  <section class="chat-panel">
    <h1>Student Advisory Chat</h1>
    <div id="chat-transcript"></div>
    <form id="chat-form">
      <textarea id="chat-input" name="content"></textarea>
      <button type="submit">Gui</button>
    </form>
  </section>
  <aside class="summary-panel">
    <div id="profile-summary"></div>
    <div id="recommendation-panel"></div>
  </aside>
</main>
{% endblock %}
```

```python
# web/app.py
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web.routes.chat_api import router as chat_router
from web.routes.pages import router as page_router
from web.routes.system import router as system_router


def build_app() -> FastAPI:
    app = FastAPI(title="Student Advisory Chat")
    app.mount("/static", StaticFiles(directory="web/static"), name="static")
    app.include_router(system_router)
    app.include_router(chat_router)
    app.include_router(page_router)
    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/web/test_chat_page.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/app.py web/routes/pages.py web/templates/base.html web/templates/chat.html tests/web/test_chat_page.py
git commit -m "feat: add public chat page shell"
```

### Task 2: Add Browser Session Persistence And Product-Level Smoke Flow

**Files:**
- Create: `web/static/js/chat.js`
- Create: `web/static/css/chat.css`
- Test: `tests/e2e/test_chat_web_flow.py`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from web.app import build_app


def test_chat_page_references_static_client_assets():
    client = TestClient(build_app())

    response = client.get("/")

    assert '/static/js/chat.js' in response.text
    assert '/static/css/chat.css' in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/e2e/test_chat_web_flow.py -v`
Expected: FAIL because `/static/js/chat.js` and `/static/css/chat.css` do not exist

- [ ] **Step 3: Write minimal implementation**

```javascript
// web/static/js/chat.js
const SESSION_KEY = "student-advisory-session-token";

async function ensureSession() {
  const current = window.localStorage.getItem(SESSION_KEY);
  if (current) {
    return current;
  }
  const response = await fetch("/api/sessions", { method: "POST" });
  const payload = await response.json();
  window.localStorage.setItem(SESSION_KEY, payload.session.session_token);
  return payload.session.session_token;
}

async function sendMessage(content) {
  const sessionToken = await ensureSession();
  return fetch(`/api/sessions/${sessionToken}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (!content) return;
    await sendMessage(content);
    input.value = "";
  });
});
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
  grid-template-columns: 2fr 1fr;
  gap: 24px;
  min-height: 100vh;
  padding: 32px;
}

.chat-panel,
.summary-panel {
  background: rgba(255, 255, 255, 0.82);
  border-radius: 20px;
  padding: 24px;
  box-shadow: 0 18px 48px rgba(31, 41, 51, 0.08);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/e2e/test_chat_web_flow.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/static/js/chat.js web/static/css/chat.css tests/e2e/test_chat_web_flow.py
git commit -m "feat: add browser chat shell assets"
```

## Self-Review

Spec coverage in this plan:
- Public student/parent-facing page: covered by Task 1.
- Browser session continuity on the same device: covered by Task 2.
- Minimal product shell on top of the API: covered by Task 1 and Task 2.

Intentional exclusions from this plan:
- No authentication.
- No operator console.
- No second frontend stack.

Plan complete and saved to `docs/superpowers/plans/2026-05-01-student-advisory-chat-v1/05-public-chat-ui.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
