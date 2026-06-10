# Slice 1 — Plan D: Register `major_resolver` and bound its tokens

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `major_resolver`'s Tier-3 LLM call (`services/profile/major_resolver.py:99`) runs under `agent_name="major_resolver"`, but the factory has no override, so it inherits the default policy with **no `max_tokens`**. Add an explicit registry entry that caps output (the response is a tiny `{"program_ids": [...]}`).

**Architecture:** One entry in `build_default_gateway`'s `agent_overrides`. No code change to the resolver itself.

**Tech Stack:** Python, pytest.

Spec: `docs/superpowers/specs/2026-06-10-slice1-cost-quickwins-design.md` §1e.

---

### Task 1: Add the `major_resolver` registry override

**Files:**
- Modify: `services/inference/factory.py:55-56`
- Test: `tests/services/inference/test_factory.py`

- [ ] **Step 1: Write the failing test**

```python
def test_major_resolver_has_bounded_token_override():
    from services import build_default_gateway
    policy = build_default_gateway().registry.resolve("major_resolver")
    assert policy.primary_model == "gemini-2.5-flash-lite"  # cheap model is intended
    assert policy.max_tokens == 100                          # bounded tiny output
    assert policy.output_mode == "json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/inference/test_factory.py::test_major_resolver_has_bounded_token_override -v`
Expected: FAIL — `max_tokens` is `None` and `output_mode` is `"free_text"` (no override).

- [ ] **Step 3: Write minimal implementation**

In `services/inference/factory.py`, add to `agent_overrides` (next to `profile_extractor`):

```python
            "major_resolver": {"output_mode": "json", "max_retries": 1, "max_tokens": 100},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/inference/test_factory.py::test_major_resolver_has_bounded_token_override -v`
Expected: PASS

- [ ] **Step 5: Regression — resolver + factory suites**

Run: `.\.venv\Scripts\python.exe -m pytest tests/services/inference/test_factory.py tests/services/profile/test_major_resolver.py -q`
Expected: PASS (the resolver already sends `output_mode="json"` on its request; the override only bounds tokens and is otherwise identical to the inherited default).

- [ ] **Step 6: Commit**

```bash
git add services/inference/factory.py tests/services/inference/test_factory.py
git commit -m "feat(inference): bound major_resolver output tokens via registry"
```

---

## Self-review notes

- `max_tokens=100` comfortably fits `{"program_ids": ["...", "..."]}` for a handful of ids.
- No fallback is configured: the resolver already degrades to the top embedding candidate on `InferenceError` (`major_resolver.py:84-86`).
