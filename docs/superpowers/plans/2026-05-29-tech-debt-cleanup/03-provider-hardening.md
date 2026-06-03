# Slice 03 — Gemini provider hardening

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Stop the Gemini provider from crashing the pipeline on malformed JSON or transient API errors. Malformed/empty JSON returns a `STRUCTURE_FAILURE` result (so the gateway's retry loop fires); hard API failures raise a typed `InferenceError`.

**Architecture:** Add `InferenceError` to the inference models and rewrite `GeminiProvider.generate()` to wrap the API call and `json.loads`. This is the foundation slices 04, 05, and 06 build on — it must land first.

**Tech Stack:** Python 3.12, `google-genai`, pytest.

**Spec:** `docs/superpowers/specs/2026-05-29-tech-debt-cleanup-design.md` (item A1)

**Depends on:** nothing (but blocks 04, 05, 06). **Branch:** `chore/stabilize-cleanup`.

> Scope is deliberately minimal-correctness: no network retry/backoff, no circuit breaker.

---

## Task 1: Add `InferenceError` and harden `GeminiProvider.generate()`

**Files:**
- Modify: `services/inference/models.py` (add exception)
- Modify: `services/inference/providers/gemini_provider.py` (rewrite `generate`, update import)
- Test: `tests/services/inference/test_gemini_provider.py` (create if absent)

- [ ] **Step 1: Write the failing tests**

Create/append `tests/services/inference/test_gemini_provider.py`:

```python
import pytest

from services.inference.models import InferenceError, InferencePolicy, InferenceRequest
from services.inference.providers.gemini_provider import GeminiProvider


class _Resp:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, text=None, exc=None):
        self._text = text
        self._exc = exc

    def generate_content(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return _Resp(self._text)


class _FakeClient:
    def __init__(self, text=None, exc=None):
        self.models = _FakeModels(text=text, exc=exc)


def _provider(client):
    provider = GeminiProvider(api_key="dummy")
    provider._client = client
    provider._api_key_present = True
    return provider


def _request():
    return InferenceRequest(
        agent_name="resolution_agent",
        task_type="conflict_tiebreak",
        system_prompt="sys",
        user_prompt="usr",
        output_mode="json",
    )


def _policy():
    return InferencePolicy(agent_name="resolution_agent", primary_model="gemini-2.5-flash-lite")


def test_malformed_json_returns_structure_failure():
    provider = _provider(_FakeClient(text="not json{"))
    result = provider.generate(_request(), _policy())
    assert result.failure_type == "STRUCTURE_FAILURE"
    assert result.parsed_data is None


def test_empty_text_returns_structure_failure():
    provider = _provider(_FakeClient(text=""))
    result = provider.generate(_request(), _policy())
    assert result.failure_type == "STRUCTURE_FAILURE"


def test_valid_json_parses():
    provider = _provider(_FakeClient(text='{"confidence": "high"}'))
    result = provider.generate(_request(), _policy())
    assert result.failure_type is None
    assert result.parsed_data == {"confidence": "high"}


def test_hard_api_error_raises_inference_error():
    provider = _provider(_FakeClient(exc=RuntimeError("429 rate limit")))
    with pytest.raises(InferenceError):
        provider.generate(_request(), _policy())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/services/inference/test_gemini_provider.py -v`
Expected: FAIL — `InferenceError` does not exist (ImportError); malformed JSON currently raises.

- [ ] **Step 3: Add `InferenceError` to `services/inference/models.py`**

At the top of `services/inference/models.py`, after the imports, add:

```python
class InferenceError(RuntimeError):
    """Raised when the inference provider hits a hard failure (network, auth, rate limit)."""
```

- [ ] **Step 4: Rewrite `GeminiProvider.generate`**

Update the import at the top of `services/inference/providers/gemini_provider.py` (line 7) to:

```python
from services.inference.models import InferenceError, InferenceResult
```

Replace the body of `generate` (lines 21-47) with:

```python
    def generate(self, request, policy):
        if not self._api_key_present:
            raise InferenceError("GEMINI_API_KEY is not configured")

        json_mode = request.output_mode == "json"
        try:
            response = self._client.models.generate_content(
                model=policy.primary_model,
                contents=request.user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=request.system_prompt,
                    temperature=request.temperature,
                    response_mime_type="application/json" if json_mode else None,
                ),
            )
        except Exception as exc:  # hard API failure: network, auth, rate limit, 5xx
            raise InferenceError(
                f"Gemini API call failed for agent={request.agent_name} "
                f"model={policy.primary_model}: {exc!r}"
            ) from exc

        text = (getattr(response, "text", "") or "").strip()

        if not json_mode:
            return InferenceResult(
                agent_name=request.agent_name,
                model=policy.primary_model,
                provider=self.provider_name,
                content=text,
            )

        if not text:
            return InferenceResult(
                agent_name=request.agent_name,
                model=policy.primary_model,
                provider=self.provider_name,
                content=text,
                failure_type="STRUCTURE_FAILURE",
            )

        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return InferenceResult(
                agent_name=request.agent_name,
                model=policy.primary_model,
                provider=self.provider_name,
                content=text,
                failure_type="STRUCTURE_FAILURE",
            )

        return InferenceResult(
            agent_name=request.agent_name,
            model=policy.primary_model,
            provider=self.provider_name,
            content=text,
            parsed_data=parsed,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/services/inference/test_gemini_provider.py -v`
Expected: PASS (all four tests).

- [ ] **Step 6: Run the broader inference suite for regressions**

Run: `.venv/Scripts/python.exe -m pytest tests/services/inference -v`
Expected: PASS. (The gateway's `STRUCTURE_FAILURE` retry path is now actually reachable.)

- [ ] **Step 7: Commit**

```bash
git add services/inference/models.py services/inference/providers/gemini_provider.py tests/services/inference/test_gemini_provider.py
git commit -m "feat: harden Gemini provider error handling and structure-failure retries"
```
