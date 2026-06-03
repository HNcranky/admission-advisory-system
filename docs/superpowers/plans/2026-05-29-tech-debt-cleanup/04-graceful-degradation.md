# Slice 04 — Graceful degradation at LLM call sites

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ensure every optional LLM call site degrades to deterministic/default output when the gateway raises `InferenceError` (or is unavailable), so a hard Gemini failure never crashes the pipeline.

**Architecture:** Add `is_available()` + `try/except InferenceError` guards to the policy-ambiguity and profile-extraction services. (`resolution_agent.resolve()` already guards with a broad `try/except` and needs no change.)

**Tech Stack:** Python 3.12, pytest.

**Spec:** `docs/superpowers/specs/2026-05-29-tech-debt-cleanup-design.md` (item A2)

**Depends on:** Slice 03 (defines `InferenceError`). **Branch:** `chore/stabilize-cleanup`.

---

## Task 1: Degrade `interpret_policy_ambiguity` on hard errors

**Files:**
- Modify: `services/policy_inference_service.py:1-25`
- Test: `tests/services/test_policy_inference_service.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Append to `tests/services/test_policy_inference_service.py`:

```python
from services.inference.models import InferenceError
from services.policy_inference_service import interpret_policy_ambiguity


class _RaisingGateway:
    def is_available(self):
        return True

    def run(self, request):
        raise InferenceError("boom")


def test_policy_ambiguity_degrades_on_inference_error():
    result = interpret_policy_ambiguity("query", ["some conflict"], _RaisingGateway())
    assert result == {"warnings": [], "requires_human_verification": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/services/test_policy_inference_service.py -v -k degrade`
Expected: FAIL — `InferenceError` propagates out of `interpret_policy_ambiguity`.

- [ ] **Step 3: Guard `interpret_policy_ambiguity`**

Replace the import line at the top of `services/policy_inference_service.py`:

```python
from services.inference.models import InferenceRequest
```

with:

```python
from services.inference.models import InferenceError, InferenceRequest
```

Replace the function body (lines 13-25) with:

```python
def interpret_policy_ambiguity(user_query: str, conflicts, gateway):
    default = {"warnings": [], "requires_human_verification": False}
    if hasattr(gateway, "is_available") and not gateway.is_available():
        return default

    payload = {"user_query": user_query, "conflicts": conflicts}
    try:
        result = gateway.run(
            InferenceRequest(
                agent_name="policy_agent",
                task_type="policy_ambiguity",
                system_prompt=POLICY_SYSTEM_PROMPT.strip(),
                user_prompt=json.dumps(payload, ensure_ascii=False),
                output_mode="json",
                temperature=0.0,
            )
        )
    except InferenceError:
        return default
    return result.parsed_data or default
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/services/test_policy_inference_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/policy_inference_service.py tests/services/test_policy_inference_service.py
git commit -m "feat: degrade policy ambiguity interpretation on hard inference errors"
```

---

## Task 2: Degrade `build_profile_with_gateway` to rule-based on hard errors

**Files:**
- Modify: `services/profile_inference_service.py:2`, `:131-147`
- Test: `tests/services/test_profile_inference_service.py` (add a test)

- [ ] **Step 1: Write the failing test**

Append to `tests/services/test_profile_inference_service.py`:

```python
from services.inference.models import InferenceError
from services.profile_inference_service import build_profile_with_gateway


class _RaisingGateway:
    def is_available(self):
        return True

    def run(self, request):
        raise InferenceError("boom")


def test_build_profile_degrades_to_rule_based_on_inference_error():
    profile = build_profile_with_gateway("Em duoc 27 diem khoi A00", _RaisingGateway())
    # Rule-based fallback still extracts the score from the query.
    assert profile.total_score == 27
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/services/test_profile_inference_service.py -v -k degrade`
Expected: FAIL — `InferenceError` propagates out of `build_profile_with_gateway`.

- [ ] **Step 3: Guard `build_profile_with_gateway`**

Update the import line (line 2) from `from services.inference.models import InferenceRequest` to:

```python
from services.inference.models import InferenceError, InferenceRequest
```

In the function body, replace (lines 135-147):

```python
    result = gateway.run(
        InferenceRequest(
            agent_name="profile_agent",
            task_type="profile_extraction",
            system_prompt=PROFILE_SYSTEM_PROMPT.format(
                major_ids=", ".join(MAJOR_ID_GUIDE)
            ).strip(),
            user_prompt=user_query,
            output_mode="json",
            temperature=0.0,
        )
    )
    return _normalize_profile(StudentProfile(**(result.parsed_data or {})))
```

with:

```python
    try:
        result = gateway.run(
            InferenceRequest(
                agent_name="profile_agent",
                task_type="profile_extraction",
                system_prompt=PROFILE_SYSTEM_PROMPT.format(
                    major_ids=", ".join(MAJOR_ID_GUIDE)
                ).strip(),
                user_prompt=user_query,
                output_mode="json",
                temperature=0.0,
            )
        )
    except InferenceError:
        return build_profile(user_query)
    return _normalize_profile(StudentProfile(**(result.parsed_data or {})))
```

(`build_profile` is already imported at the top of the file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/services/test_profile_inference_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/profile_inference_service.py tests/services/test_profile_inference_service.py
git commit -m "feat: degrade profile extraction to rule-based on hard inference errors"
```
