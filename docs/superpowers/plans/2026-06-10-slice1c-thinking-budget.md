# Slice 1 — Plan C: Per-agent thinking budget + disable on knowledge_qa

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the model registry set a Gemini `thinking_budget` per agent, and set it to `0` for `knowledge_qa_agent` — the only high-frequency agent on `gemini-2.5-flash` (which defaults to billed dynamic thinking). Flash-Lite agents are unaffected (they do not think by default). `synthesis_agent` is intentionally left untouched (deferred to the Slice 4 eval).

**Architecture:** Add an optional `thinking_budget` to `InferencePolicy`, surface it via `ModelRegistry.resolve`, and have `GeminiProvider._call` attach `types.ThinkingConfig(thinking_budget=n)` only when set. Default `None` ⇒ no `thinking_config` ⇒ byte-identical to today.

**Tech Stack:** Python, pytest, `google.genai.types.ThinkingConfig`.

Spec: `docs/superpowers/specs/2026-06-10-slice1-cost-quickwins-design.md` §1a. Grounding: https://ai.google.dev/gemini-api/docs/thinking

---

### Task 1: `thinking_budget` field on `InferencePolicy` + registry plumbing

**Files:**
- Modify: `services/inference/models.py:24-31`
- Modify: `services/inference/registry.py:12-23`
- Test: `tests/services/inference/test_registry.py`

- [ ] **Step 1: Write the failing test**

```python
def test_resolve_passes_thinking_budget_when_set():
    from services.inference.registry import ModelRegistry
    registry = ModelRegistry(
        default_model="gemini-2.5-flash-lite",
        agent_overrides={"qa": {"thinking_budget": 0}},
    )
    assert registry.resolve("qa").thinking_budget == 0


def test_resolve_thinking_budget_defaults_to_none():
    from services.inference.registry import ModelRegistry
    registry = ModelRegistry(default_model="gemini-2.5-flash-lite")
    assert registry.resolve("anything").thinking_budget is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/inference/test_registry.py::test_resolve_passes_thinking_budget_when_set tests/services/inference/test_registry.py::test_resolve_thinking_budget_defaults_to_none -v`
Expected: FAIL — `InferencePolicy` has no attribute `thinking_budget`.

- [ ] **Step 3: Write minimal implementation**

In `services/inference/models.py`, add the field to `InferencePolicy`:

```python
class InferencePolicy(BaseModel):
    agent_name: str
    primary_model: str
    fallback_model: Optional[str] = None
    allow_fallback: bool = False
    output_mode: str = "free_text"
    max_retries: int = 1
    max_tokens: Optional[int] = None
    thinking_budget: Optional[int] = None
```

In `services/inference/registry.py`, read it in `resolve`:

```python
    def resolve(self, agent_name: str) -> InferencePolicy:
        override = self.agent_overrides.get(agent_name, {})
        raw_max_tokens = override.get("max_tokens")
        raw_thinking = override.get("thinking_budget")
        return InferencePolicy(
            agent_name=agent_name,
            primary_model=str(override.get("primary_model", self.default_model)),
            fallback_model=override.get("fallback_model"),
            allow_fallback=bool(override.get("allow_fallback", False)),
            output_mode=str(override.get("output_mode", "free_text")),
            max_retries=int(override.get("max_retries", 1)),
            max_tokens=int(raw_max_tokens) if raw_max_tokens is not None else None,
            thinking_budget=int(raw_thinking) if raw_thinking is not None else None,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/inference/test_registry.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/inference/models.py services/inference/registry.py tests/services/inference/test_registry.py
git commit -m "feat(inference): add per-agent thinking_budget to policy and registry"
```

---

### Task 2: Provider attaches `ThinkingConfig` only when budget is set

**Files:**
- Modify: `services/inference/providers/gemini_provider.py:36-56`
- Test: `tests/services/inference/test_gemini_provider.py`

- [ ] **Step 1: Write the failing test**

```python
def test_thinking_budget_sets_thinking_config():
    captured = {}
    pool = _pool({"k1": FakeClient(text='{"ok": true}', captured=captured)})
    provider = GeminiProvider(pool=pool)
    policy = InferencePolicy(agent_name="qa", primary_model="gemini-2.5-flash", thinking_budget=0)
    provider.generate(_request(), policy)
    assert captured["config"].thinking_config is not None
    assert captured["config"].thinking_config.thinking_budget == 0


def test_no_thinking_budget_leaves_thinking_config_unset():
    captured = {}
    pool = _pool({"k1": FakeClient(text='{"ok": true}', captured=captured)})
    provider = GeminiProvider(pool=pool)
    provider.generate(_request(), _policy())  # _policy() → thinking_budget None
    assert captured["config"].thinking_config is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/inference/test_gemini_provider.py::test_thinking_budget_sets_thinking_config -v`
Expected: FAIL — `thinking_config` is `None` (provider never sets it).

- [ ] **Step 3: Write minimal implementation**

In `services/inference/providers/gemini_provider.py`, build the config dict conditionally:

```python
    @staticmethod
    def _call(client, request, policy):
        json_mode = request.output_mode == "json"
        if request.media:
            contents = [
                types.Part.from_bytes(data=data, mime_type=mime)
                for mime, data in request.media
            ] + [request.user_prompt]
        else:
            contents = request.user_prompt

        config_kwargs = dict(
            system_instruction=request.system_prompt,
            temperature=request.temperature,
            response_mime_type="application/json" if json_mode else None,
            max_output_tokens=policy.max_tokens,
        )
        if policy.thinking_budget is not None:
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=policy.thinking_budget
            )

        return client.models.generate_content(
            model=policy.primary_model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/inference/test_gemini_provider.py -q`
Expected: PASS (all existing provider tests still pass — default path adds no `thinking_config`).

- [ ] **Step 5: Commit**

```bash
git add services/inference/providers/gemini_provider.py tests/services/inference/test_gemini_provider.py
git commit -m "feat(inference): pass ThinkingConfig to Gemini when a budget is set"
```

---

### Task 3: Disable thinking for `knowledge_qa_agent` in the factory

**Files:**
- Modify: `services/inference/factory.py:31-38`
- Test: `tests/services/inference/test_factory.py`

- [ ] **Step 1: Write the failing test**

```python
def test_knowledge_qa_agent_disables_thinking():
    from services import build_default_gateway
    gateway = build_default_gateway()
    assert gateway.registry.resolve("knowledge_qa_agent").thinking_budget == 0


def test_synthesis_agent_keeps_default_thinking():
    from services import build_default_gateway
    gateway = build_default_gateway()
    # Deferred to Slice 4 eval — must remain unset (default dynamic thinking).
    assert gateway.registry.resolve("synthesis_agent").thinking_budget is None
```

(If `test_factory.py` imports `build_default_gateway` differently, match the existing import style in that file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/inference/test_factory.py::test_knowledge_qa_agent_disables_thinking -v`
Expected: FAIL — `thinking_budget` is `None`.

- [ ] **Step 3: Write minimal implementation**

In `services/inference/factory.py`, add `"thinking_budget": 0` to the `knowledge_qa_agent` override only:

```python
            "knowledge_qa_agent": {
                "primary_model": "gemini-2.5-flash",
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash-lite",
                "max_tokens": 800,
                "thinking_budget": 0,
            },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/inference/test_factory.py -q`
Expected: PASS

- [ ] **Step 5: Run the inference suite**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/inference/ -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/inference/factory.py tests/services/inference/test_factory.py
git commit -m "feat(inference): disable thinking for knowledge_qa_agent"
```

---

## Self-review notes

- Flash-Lite agents are untouched and unaffected (no `thinking_config`, and Flash-Lite doesn't think by default).
- `synthesis_agent` deliberately left with default thinking — naturalness is a project goal; the toggle is gated behind the Slice 4 eval.
- The `knowledge_qa_agent` fallback model is Flash-Lite; `thinking_budget=0` is harmless there too.
