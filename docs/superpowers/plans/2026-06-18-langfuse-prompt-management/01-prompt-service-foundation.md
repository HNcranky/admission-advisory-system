# Langfuse Prompt Management — Plan 01: PromptService Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `PromptService` that resolves a named system prompt to text + a linkable Langfuse handle, falling back to an in-code constant when Langfuse is disabled or unreachable.

**Architecture:** New module `observability/prompts.py` sits next to `langfuse_client.py` and reuses its `get_langfuse()` singleton. `PromptService.get(name, fallback=..., variables=...)` returns a `CompiledPrompt(text, handle, is_fallback)`. When Langfuse is disabled it short-circuits to the fallback with **no network call** — identical behavior to today. No call sites change in this plan; the service is wired up in Plan 03.

**Tech Stack:** Python, Pydantic v2 codebase, `langfuse>=3,<4`, pytest. Spec: `docs/superpowers/specs/2026-06-18-langfuse-prompt-management-design.md` §3.1, §5.

---

### Task 1: `CompiledPrompt` + `PromptService.get` with disabled/fallback path

**Files:**
- Create: `observability/prompts.py`
- Test: `tests/observability/test_prompts.py`

- [ ] **Step 1: Write the failing test**

Create `tests/observability/test_prompts.py`:

```python
import observability.prompts as prompts
from observability.prompts import CompiledPrompt, PromptService


def test_disabled_returns_fallback_without_network(monkeypatch):
    calls = []

    def _no_client():
        calls.append("get_langfuse")
        return None

    monkeypatch.setattr(prompts, "get_langfuse", _no_client)
    svc = PromptService()
    cp = svc.get("intent-router", fallback="FALLBACK TEXT")
    assert isinstance(cp, CompiledPrompt)
    assert cp.text == "FALLBACK TEXT"
    assert cp.handle is None
    assert cp.is_fallback is True
    # get_langfuse consulted, but no prompt fetch attempted (no client)
    assert calls == ["get_langfuse"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/observability/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'observability.prompts'`

(Use the project venv: `.venv/bin/python -m pytest ...` on Linux, `.\.venv\Scripts\python.exe -m pytest ...` on Windows.)

- [ ] **Step 3: Write minimal implementation**

Create `observability/prompts.py`:

```python
import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from observability.langfuse_client import get_langfuse

logger = logging.getLogger(__name__)

_DEFAULT_LABEL = "production"
_DEFAULT_CACHE_TTL = 300


def _label() -> str:
    return os.getenv("LANGFUSE_PROMPT_LABEL", _DEFAULT_LABEL)


def _cache_ttl() -> int:
    raw = os.getenv("LANGFUSE_PROMPT_CACHE_TTL_SECONDS", str(_DEFAULT_CACHE_TTL))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_CACHE_TTL


@dataclass
class CompiledPrompt:
    """Resolved system prompt. ``handle`` is the Langfuse prompt client used to
    link a generation to its prompt version; None on fallback (nothing to link)."""

    text: str
    handle: Optional[Any] = None
    is_fallback: bool = False


class PromptService:
    """Resolve a named prompt to text + a linkable handle. Mirrors the
    graceful-degradation contract of build_default_gateway()/get_langfuse():
    callers never special-case Langfuse being off or down."""

    def get(self, name: str, *, fallback: str, variables: Optional[dict] = None) -> CompiledPrompt:
        client = get_langfuse()
        if client is None:
            return CompiledPrompt(text=fallback, handle=None, is_fallback=True)
        raise NotImplementedError  # enabled path implemented in Task 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/observability/test_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add observability/prompts.py tests/observability/test_prompts.py
git commit -m "feat(prompts): PromptService skeleton with disabled fallback path"
```

---

### Task 2: Enabled path — fetch, compile, link handle

**Files:**
- Modify: `observability/prompts.py`
- Test: `tests/observability/test_prompts.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/observability/test_prompts.py`:

```python
class _FakePrompt:
    def __init__(self, text, is_fallback=False):
        self._text = text
        self.is_fallback = is_fallback

    def compile(self, **kwargs):
        text = self._text
        for key, value in kwargs.items():
            text = text.replace("{{" + key + "}}", str(value))
        return text


class _FakeLangfuse:
    def __init__(self, prompt=None, raises=False):
        self._prompt = prompt
        self._raises = raises
        self.calls = []

    def get_prompt(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if self._raises:
            raise RuntimeError("langfuse down")
        return self._prompt


def test_enabled_hit_returns_text_and_handle(monkeypatch):
    fake = _FakeLangfuse(prompt=_FakePrompt("FROM LANGFUSE"))
    monkeypatch.setattr(prompts, "get_langfuse", lambda: fake)
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "production")
    monkeypatch.setenv("LANGFUSE_PROMPT_CACHE_TTL_SECONDS", "42")
    svc = PromptService()
    cp = svc.get("intent-router", fallback="FALLBACK")
    assert cp.text == "FROM LANGFUSE"
    assert cp.handle is fake._prompt   # the prompt client, for generation linking
    assert cp.is_fallback is False
    name, kwargs = fake.calls[0]
    assert name == "intent-router"
    assert kwargs["label"] == "production"
    assert kwargs["cache_ttl_seconds"] == 42
    assert kwargs["fallback"] == "FALLBACK"
    assert kwargs["type"] == "text"


def test_enabled_error_returns_fallback(monkeypatch):
    fake = _FakeLangfuse(raises=True)
    monkeypatch.setattr(prompts, "get_langfuse", lambda: fake)
    svc = PromptService()
    cp = svc.get("intent-router", fallback="FALLBACK")
    assert cp.text == "FALLBACK"
    assert cp.handle is None
    assert cp.is_fallback is True


def test_sdk_fallback_prompt_is_not_linked(monkeypatch):
    # When the Langfuse SDK itself serves the fallback (fetch failed but
    # fallback= was given), the returned client has no real version — do not link.
    fake = _FakeLangfuse(prompt=_FakePrompt("FALLBACK", is_fallback=True))
    monkeypatch.setattr(prompts, "get_langfuse", lambda: fake)
    svc = PromptService()
    cp = svc.get("intent-router", fallback="FALLBACK")
    assert cp.text == "FALLBACK"
    assert cp.handle is None
    assert cp.is_fallback is True


def test_compile_substitutes_variables(monkeypatch):
    fake = _FakeLangfuse(prompt=_FakePrompt("Năm tuyển sinh {{year}}"))
    monkeypatch.setattr(prompts, "get_langfuse", lambda: fake)
    svc = PromptService()
    cp = svc.get("fact-extractor", fallback="X", variables={"year": 2026})
    assert cp.text == "Năm tuyển sinh 2026"
    assert cp.handle is fake._prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/observability/test_prompts.py -v`
Expected: the 4 new tests FAIL with `NotImplementedError`

- [ ] **Step 3: Replace the `raise NotImplementedError` with the enabled path**

In `observability/prompts.py`, replace the `raise NotImplementedError  # enabled path implemented in Task 2` line with:

```python
        try:
            prompt = client.get_prompt(
                name,
                label=_label(),
                cache_ttl_seconds=_cache_ttl(),
                fallback=fallback,
                type="text",
            )
            text = prompt.compile(**(variables or {}))
            is_fallback = bool(getattr(prompt, "is_fallback", False))
            # Never link a fallback client: it maps to no stored prompt version.
            handle = None if is_fallback else prompt
            return CompiledPrompt(text=text, handle=handle, is_fallback=is_fallback)
        except Exception as exc:  # fetch/compile failure must not break the call site
            logger.warning("prompt fetch failed for %s; using fallback: %r", name, exc)
            return CompiledPrompt(text=fallback, handle=None, is_fallback=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/observability/test_prompts.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add observability/prompts.py tests/observability/test_prompts.py
git commit -m "feat(prompts): fetch/compile prompt and expose linkable handle"
```

---

### Task 3: Module singleton `get_prompt_service()`

**Files:**
- Modify: `observability/prompts.py`
- Test: `tests/observability/test_prompts.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/observability/test_prompts.py`:

```python
def test_get_prompt_service_is_singleton():
    from observability.prompts import get_prompt_service
    assert get_prompt_service() is get_prompt_service()
    assert isinstance(get_prompt_service(), PromptService)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/observability/test_prompts.py::test_get_prompt_service_is_singleton -v`
Expected: FAIL — `ImportError: cannot import name 'get_prompt_service'`

- [ ] **Step 3: Add the singleton at the end of `observability/prompts.py`**

```python
_service: Optional[PromptService] = None


def get_prompt_service() -> PromptService:
    """Process-wide PromptService, mirroring get_langfuse()."""
    global _service
    if _service is None:
        _service = PromptService()
    return _service
```

- [ ] **Step 4: Run the full prompts test file**

Run: `python -m pytest tests/observability/test_prompts.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add observability/prompts.py tests/observability/test_prompts.py
git commit -m "feat(prompts): add get_prompt_service singleton accessor"
```

---

### Task 4: Document config env vars in `.env.example`

**Files:**
- Modify: `.env.example` (Observability section, after `LANGFUSE_RELEASE=`)

- [ ] **Step 1: Add the new vars**

In `.env.example`, immediately after the `LANGFUSE_RELEASE=` line, add:

```bash
# --- Langfuse prompt management ---
# Label fetched at runtime (move it in the UI to deploy/rollback). Dev can set
# "latest" to pick up edits immediately.
LANGFUSE_PROMPT_LABEL=production
# In-process cache TTL for fetched prompts (seconds). The SDK refreshes in the
# background; the in-code fallback covers any fetch failure.
LANGFUSE_PROMPT_CACHE_TTL_SECONDS=300
```

- [ ] **Step 2: Verify the file parses (no test; visual check)**

Run: `grep -n "LANGFUSE_PROMPT" .env.example`
Expected: both new lines printed.

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs(env): document Langfuse prompt label/cache-ttl vars"
```

---

## Self-Review

- **Spec coverage:** §3.1 PromptService (Tasks 1–3), §3.5 config (Task 4), §5 PromptService tests (Tasks 1–3). Generation linking (§3.2) and call-site swap (§3.3) + seeding (§3.4) are Plans 02 and 03.
- **Placeholders:** none — `NotImplementedError` is an intentional Task-1→Task-2 TDD seam, replaced in Task 2 Step 3.
- **Type consistency:** `CompiledPrompt(text, handle, is_fallback)`, `PromptService.get(name, *, fallback, variables)`, `get_prompt_service()` consistent across tasks and reused verbatim in Plan 03.
