# Langfuse Prompt Management — Plan 03: Pilot Migration + Seed Script

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the 3 pilot agents (`intent_router`, `knowledge_qa`, `synthesis`) to resolve their system prompt via `PromptService`, pass the linkable handle into the request, and add a one-off script that seeds the prompts into Langfuse.

**Architecture:** Each call site swaps its inline `system_prompt=CONST` for `cp = get_prompt_service().get("<name>", fallback=CONST)` then `system_prompt=cp.text, prompt=cp.handle`. The constant stays in the module as the fallback. With Langfuse disabled (default/CI), `cp.text` is byte-identical to the old constant and `cp.handle` is None — provably zero regression. `scripts/seed_langfuse_prompts.py` bootstraps the three prompts in Langfuse.

**Tech Stack:** Python, `langfuse>=3,<4`, pytest. **Depends on Plan 01 (`PromptService`) and Plan 02 (`InferenceRequest.prompt` + gateway/record_generation linking).** Spec: `docs/superpowers/specs/2026-06-18-langfuse-prompt-management-design.md` §3.3, §3.4, §5.

---

### Task 1: Migrate `intent_router`

**Files:**
- Modify: `services/chat/intent_router.py` (import + call site ~219-229)
- Test: `tests/services/chat/test_intent_router_prompt_source.py`

- [ ] **Step 1: Write the tests (one driving, one pin)**

Create `tests/services/chat/test_intent_router_prompt_source.py`:

```python
import observability.prompts as prompts
from services.chat.intent_router import INTENT_SYSTEM_PROMPT, IntentRouter
from services.chat.profile_state import ChatProfileState
from services.inference.models import InferenceResult


class _CapturingGateway:
    def __init__(self):
        self.request = None

    def is_available(self):
        return True

    def run(self, request):
        self.request = request
        return InferenceResult(
            agent_name=request.agent_name, model="m", provider="fake",
            content='{"route": "CLARIFICATION"}',
            parsed_data={"route": "CLARIFICATION"},
        )


class _FakePrompt:
    is_fallback = False

    def __init__(self, text):
        self._text = text

    def compile(self, **kwargs):
        return self._text


class _FakeLangfuse:
    def __init__(self, prompt):
        self._prompt = prompt

    def get_prompt(self, name, **kwargs):
        return self._prompt


# DRIVING test: fails before the swap (call site ignores PromptService), green after.
def test_uses_langfuse_text_and_handle_when_enabled(monkeypatch):
    handle = _FakePrompt("LANGFUSE INTENT PROMPT")
    monkeypatch.setattr(prompts, "get_langfuse", lambda: _FakeLangfuse(handle))
    gw = _CapturingGateway()
    router = IntentRouter(gateway=gw)
    router.classify("xin chào", ChatProfileState())
    assert gw.request.system_prompt == "LANGFUSE INTENT PROMPT"
    assert gw.request.prompt is handle


# PIN test: with Langfuse off, behaviour is byte-identical to today (no regression).
def test_system_prompt_matches_constant_when_langfuse_disabled(monkeypatch):
    monkeypatch.setattr(prompts, "get_langfuse", lambda: None)
    gw = _CapturingGateway()
    router = IntentRouter(gateway=gw)
    router.classify("xin chào", ChatProfileState())
    assert gw.request.system_prompt == INTENT_SYSTEM_PROMPT
    assert gw.request.prompt is None
```

> If `ChatProfileState()` requires arguments, construct it the way existing
> `tests/services/chat/` tests do — check a sibling test for the exact call.

- [ ] **Step 2: Run tests to verify the driving test fails**

Run: `python -m pytest tests/services/chat/test_intent_router_prompt_source.py -v`
Expected: `test_uses_langfuse_text_and_handle_when_enabled` FAILS (call site still passes `INTENT_SYSTEM_PROMPT` and no handle — assertion error). The pin test already passes (it characterizes current behaviour).

- [ ] **Step 3: Swap the call site**

In `services/chat/intent_router.py`, add the import near the other `services` imports at the top:

```python
from observability.prompts import get_prompt_service
```

Then in `classify(...)`, replace the `self._gateway.run(InferenceRequest(...))` block so the system prompt comes from `PromptService`:

```python
            cp = get_prompt_service().get("intent-router", fallback=INTENT_SYSTEM_PROMPT)
            result = self._gateway.run(
                InferenceRequest(
                    agent_name="intent_router",
                    task_type="intent_classification",
                    system_prompt=cp.text,
                    prompt=cp.handle,
                    user_prompt=self._build_user_prompt(message, profile_state, history),
                    output_mode="json",
                    response_schema=IntentResult,
                    temperature=0.0,
                )
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/chat/test_intent_router_prompt_source.py -v`
Expected: PASS

- [ ] **Step 5: Run existing intent-router tests for regressions**

Run: `python -m pytest tests/services/chat -k intent -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add services/chat/intent_router.py tests/services/chat/test_intent_router_prompt_source.py
git commit -m "feat(intent-router): resolve system prompt via Langfuse PromptService"
```

---

### Task 2: Migrate `knowledge_qa`

**Files:**
- Modify: `services/knowledge/qa_service.py` (import + call site ~133-142)
- Test: `tests/services/knowledge/test_qa_prompt_source.py`

- [ ] **Step 1: Write the tests (one driving, one pin)**

Create `tests/services/knowledge/test_qa_prompt_source.py`:

```python
import observability.prompts as prompts
from services.knowledge.qa_service import KNOWLEDGE_QA_SYSTEM_PROMPT, KnowledgeQAService
from services.inference.models import InferenceResult


class _CapturingGateway:
    def __init__(self):
        self.request = None

    def run(self, request):
        self.request = request
        # empty answer => _generate returns no-data without touching citations
        return InferenceResult(
            agent_name=request.agent_name, model="m", provider="fake",
            content='{"answer": ""}', parsed_data={"answer": ""},
        )


class _FakePrompt:
    is_fallback = False

    def __init__(self, text):
        self._text = text

    def compile(self, **kwargs):
        return self._text


class _FakeLangfuse:
    def __init__(self, prompt):
        self._prompt = prompt

    def get_prompt(self, name, **kwargs):
        return self._prompt


# DRIVING test: fails before the swap, green after.
def test_uses_langfuse_text_and_handle_when_enabled(monkeypatch):
    handle = _FakePrompt("LANGFUSE QA PROMPT")
    monkeypatch.setattr(prompts, "get_langfuse", lambda: _FakeLangfuse(handle))
    gw = _CapturingGateway()
    svc = KnowledgeQAService(chunk_repository=object(), embedder=object(), gateway=gw)
    svc._generate(question="học phí?", chunks=[], confidence=0.9, conversation_context="")
    assert gw.request.system_prompt == "LANGFUSE QA PROMPT"
    assert gw.request.prompt is handle


# PIN test: with Langfuse off, behaviour is byte-identical to today.
def test_system_prompt_matches_constant_when_langfuse_disabled(monkeypatch):
    monkeypatch.setattr(prompts, "get_langfuse", lambda: None)
    gw = _CapturingGateway()
    svc = KnowledgeQAService(chunk_repository=object(), embedder=object(), gateway=gw)
    svc._generate(question="học phí?", chunks=[], confidence=0.9, conversation_context="")
    assert gw.request.system_prompt == KNOWLEDGE_QA_SYSTEM_PROMPT
    assert gw.request.prompt is None
```

- [ ] **Step 2: Run tests to verify the driving test fails**

Run: `python -m pytest tests/services/knowledge/test_qa_prompt_source.py -v`
Expected: `test_uses_langfuse_text_and_handle_when_enabled` FAILS (call site still uses the raw constant, no `prompt`). The pin test passes.

- [ ] **Step 3: Swap the call site**

In `services/knowledge/qa_service.py`, add the import near the other `services` imports:

```python
from observability.prompts import get_prompt_service
```

Then in `_generate(...)`, replace the `self._gateway.run(InferenceRequest(...))` block:

```python
            cp = get_prompt_service().get("knowledge-qa", fallback=KNOWLEDGE_QA_SYSTEM_PROMPT)
            result = self._gateway.run(
                InferenceRequest(
                    agent_name="knowledge_qa_agent",
                    task_type="knowledge_qa",
                    system_prompt=cp.text,
                    prompt=cp.handle,
                    user_prompt=self._build_user_prompt(question, chunks, conversation_context),
                    output_mode="json",
                    temperature=0.0,
                )
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/knowledge/test_qa_prompt_source.py -v`
Expected: PASS

- [ ] **Step 5: Run existing knowledge tests for regressions**

Run: `python -m pytest tests/services/knowledge -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add services/knowledge/qa_service.py tests/services/knowledge/test_qa_prompt_source.py
git commit -m "feat(knowledge-qa): resolve system prompt via Langfuse PromptService"
```

---

### Task 3: Migrate `synthesis`

**Files:**
- Modify: `services/chat/synthesis_agent.py` (import + call site ~46-55)
- Test: `tests/services/chat/test_synthesis_prompt_source.py`

- [ ] **Step 1: Write the tests (one driving, one pin)**

Create `tests/services/chat/test_synthesis_prompt_source.py`:

```python
import observability.prompts as prompts
from services.chat.hybrid_models import AdvisoryBlock
from services.chat.synthesis_agent import SYNTHESIS_SYSTEM_PROMPT, SynthesisAgent
from services.inference.models import InferenceResult


class _CapturingGateway:
    def __init__(self):
        self.request = None

    def is_available(self):
        return True

    def run(self, request):
        self.request = request
        return InferenceResult(
            agent_name=request.agent_name, model="m", provider="fake",
            content="câu trả lời tổng hợp",
        )


class _FakePrompt:
    is_fallback = False

    def __init__(self, text):
        self._text = text

    def compile(self, **kwargs):
        return self._text


class _FakeLangfuse:
    def __init__(self, prompt):
        self._prompt = prompt

    def get_prompt(self, name, **kwargs):
        return self._prompt


# DRIVING test: fails before the swap, green after.
def test_uses_langfuse_text_and_handle_when_enabled(monkeypatch):
    handle = _FakePrompt("LANGFUSE SYNTHESIS PROMPT")
    monkeypatch.setattr(prompts, "get_langfuse", lambda: _FakeLangfuse(handle))
    gw = _CapturingGateway()
    agent = SynthesisAgent(gateway=gw)
    advisory = AdvisoryBlock(has_data=True, answer="A", sources=[])
    agent.synthesize(advisory, knowledge=[], question="so sánh?")
    assert gw.request.system_prompt == "LANGFUSE SYNTHESIS PROMPT"
    assert gw.request.prompt is handle


# PIN test: with Langfuse off, behaviour is byte-identical to today.
def test_system_prompt_matches_constant_when_langfuse_disabled(monkeypatch):
    monkeypatch.setattr(prompts, "get_langfuse", lambda: None)
    gw = _CapturingGateway()
    agent = SynthesisAgent(gateway=gw)
    advisory = AdvisoryBlock(has_data=True, answer="A", sources=[])
    agent.synthesize(advisory, knowledge=[], question="so sánh?")
    assert gw.request.system_prompt == SYNTHESIS_SYSTEM_PROMPT
    assert gw.request.prompt is None
```

> If `AdvisoryBlock`'s constructor differs, mirror an existing
> `tests/services/chat/` hybrid/synthesis test for the exact fields.

- [ ] **Step 2: Run tests to verify the driving test fails**

Run: `python -m pytest tests/services/chat/test_synthesis_prompt_source.py -v`
Expected: `test_uses_langfuse_text_and_handle_when_enabled` FAILS (call site still uses the raw constant). The pin test passes.

- [ ] **Step 3: Swap the call site**

In `services/chat/synthesis_agent.py`, add the import near the top:

```python
from observability.prompts import get_prompt_service
```

Then in `_llm_synthesize(...)`, replace the `self._gateway.run(InferenceRequest(...))` block:

```python
        cp = get_prompt_service().get("synthesis", fallback=SYNTHESIS_SYSTEM_PROMPT)
        result = self._gateway.run(
            InferenceRequest(
                agent_name="synthesis_agent",
                task_type="hybrid_synthesis",
                system_prompt=cp.text,
                prompt=cp.handle,
                user_prompt=self._build_user_prompt(advisory, knowledge, question),
                output_mode="free_text",
                temperature=0.0,
            )
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/chat/test_synthesis_prompt_source.py -v`
Expected: PASS

- [ ] **Step 5: Run existing chat tests for regressions**

Run: `python -m pytest tests/services/chat -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add services/chat/synthesis_agent.py tests/services/chat/test_synthesis_prompt_source.py
git commit -m "feat(synthesis): resolve system prompt via Langfuse PromptService"
```

---

### Task 4: Seed script `scripts/seed_langfuse_prompts.py`

**Files:**
- Create: `scripts/seed_langfuse_prompts.py`

> `scripts/` is not part of the test suite (repo convention) — no automated test. Verified by a manual run against a configured Langfuse.

- [ ] **Step 1: Write the script**

Create `scripts/seed_langfuse_prompts.py`:

```python
"""One-off: seed managed system prompts into Langfuse as the production version.

Run once after Langfuse is configured (ADVISORY_LANGFUSE_ENABLED=true + keys):

    .venv/bin/python -m scripts.seed_langfuse_prompts      # Linux
    .\\.venv\\Scripts\\python.exe -m scripts.seed_langfuse_prompts   # Windows

Idempotent: a prompt that already exists is skipped, so re-runs never create
spurious versions. Not part of the test suite (scripts/ convention).
"""
import logging

from observability.langfuse_client import flush_langfuse, get_langfuse
from services.chat.intent_router import INTENT_SYSTEM_PROMPT
from services.chat.synthesis_agent import SYNTHESIS_SYSTEM_PROMPT
from services.knowledge.qa_service import KNOWLEDGE_QA_SYSTEM_PROMPT

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed_langfuse_prompts")

# Langfuse prompt name -> in-code fallback constant (same names PromptService.get uses).
MANAGED_PROMPTS = {
    "intent-router": INTENT_SYSTEM_PROMPT,
    "knowledge-qa": KNOWLEDGE_QA_SYSTEM_PROMPT,
    "synthesis": SYNTHESIS_SYSTEM_PROMPT,
}


def _exists(client, name: str) -> bool:
    try:
        client.get_prompt(name, cache_ttl_seconds=0)
        return True
    except Exception:
        return False


def main() -> int:
    client = get_langfuse()
    if client is None:
        logger.error(
            "Langfuse disabled/misconfigured; set ADVISORY_LANGFUSE_ENABLED=true "
            "and LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY before seeding."
        )
        return 1
    for name, text in MANAGED_PROMPTS.items():
        if _exists(client, name):
            logger.info("skip %s (already exists)", name)
            continue
        client.create_prompt(name=name, prompt=text, labels=["production"], type="text")
        logger.info("created %s (labelled production)", name)
    flush_langfuse()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke-check it imports (no Langfuse needed — exits cleanly when disabled)**

Run: `python -m scripts.seed_langfuse_prompts`
Expected (Langfuse disabled): logs `Langfuse disabled/misconfigured ...` and exits non-zero. No traceback.

- [ ] **Step 3: Commit**

```bash
git add scripts/seed_langfuse_prompts.py
git commit -m "feat(scripts): seed pilot system prompts into Langfuse"
```

---

### Task 5: Full-suite regression gate

- [ ] **Step 1: Run the whole suite**

Run: `python -m pytest -q`
Expected: green (same pass count as before the feature, plus the new tests). Tests run against the auto-created `admission_test` DB; Langfuse is disabled in tests so all call sites use the in-code fallback.

- [ ] **Step 2: If anything is red, fix before proceeding**

Investigate failures; the most likely cause is a constructor signature mismatch in a characterization test (`ChatProfileState`, `AdvisoryBlock`) — align it with a sibling test. Do not weaken the `system_prompt == CONST` / `prompt is None` assertions.

---

## Manual verification (post-merge, against a live Langfuse)

Not automated; do once after seeding:

1. Set `ADVISORY_LANGFUSE_ENABLED=true` + keys + `LANGFUSE_HOST`.
2. Run `python -m scripts.seed_langfuse_prompts` → three prompts appear in the Langfuse UI, labelled `production`.
3. Exercise a chat turn (intent → knowledge QA / synthesis). In Langfuse, the generations show a linked prompt + version.
4. Edit `intent-router` in the UI, move the `production` label to the new version, wait past `LANGFUSE_PROMPT_CACHE_TTL_SECONDS` → the app uses the new text without a redeploy.

---

## Self-Review

- **Spec coverage:** §3.3 call-site swaps (Tasks 1–3), §3.4 seed script (Task 4), §5 characterization tests (Tasks 1–3) + full-suite gate (Task 5) + manual live verification.
- **Placeholders:** none. The two `>` notes (ChatProfileState / AdvisoryBlock constructors) point the engineer at sibling tests for exact constructor args rather than guessing — they are guidance, not deferred work.
- **Type consistency:** all three call sites use the identical recipe `cp = get_prompt_service().get(<name>, fallback=CONST)` → `system_prompt=cp.text, prompt=cp.handle`. Prompt names (`intent-router`, `knowledge-qa`, `synthesis`) match `MANAGED_PROMPTS` in the seed script exactly.
- **Dependency note:** requires Plan 02's `InferenceRequest.prompt` field; without it, `prompt=cp.handle` raises at request construction.
