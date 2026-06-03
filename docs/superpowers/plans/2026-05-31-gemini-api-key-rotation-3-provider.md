# Gemini API Key Rotation — Plan 3/3: Provider Failover + Verification

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Repo convention (overrides skill default):** This repo's CLAUDE.md says *never* run `git commit`/`git push` — the user commits. Every task therefore ends with a **Stage** step (`git add` only). Do NOT commit.

**Goal:** Viết lại `GeminiProvider.generate()` thành vòng lặp xoay key qua pool (gặp lỗi gắn-với-key thì penalize + thử key kế; hết key khỏe → `InferenceError`), rồi chạy regression đầy đủ + smoke thủ công và cập nhật trạng thái spec.

**Dependencies:** **Plan 1** (`gemini_errors.py`) và **Plan 2** (`key_pool.py`) phải xong trước — provider import `is_rotatable_error`/`parse_retry_delay` và `GeminiKeyPool`/`get_key_pool`.
**Downstream:** Không. Đây là plan cuối; `LLMGateway` và `ModelRegistry` không đổi.

**Tech Stack:** Python 3.12, `google-genai` SDK, pydantic v2, pytest. Chạy test bằng `./.venv/Scripts/python.exe -m pytest`.

**Spec:** `docs/superpowers/specs/2026-05-31-gemini-api-key-rotation-design.md`
**Overview:** `docs/superpowers/plans/2026-05-31-gemini-api-key-rotation.md`

---

## File Structure (plan này)

| File | Trách nhiệm | Hành động |
|---|---|---|
| `services/inference/providers/gemini_provider.py` | `generate()` xoay key qua pool; tách `_call()` + `_build_result()`. | Modify (rewrite) |
| `tests/services/inference/test_gemini_provider.py` | Viết lại sang inject pool/client_factory + test failover. | Modify (rewrite) |
| `docs/superpowers/specs/2026-05-31-gemini-api-key-rotation-design.md` | Đổi `Status: Draft → Implemented`. | Modify |

---

## Task 4: Provider failover — rewrite `GeminiProvider`

**Files:**
- Modify: `services/inference/providers/gemini_provider.py` (rewrite whole file)
- Test: `tests/services/inference/test_gemini_provider.py` (rewrite whole file)

- [ ] **Step 1: Rewrite the test file (failing tests)**

Replace the entire contents of `tests/services/inference/test_gemini_provider.py`:

```python
from types import SimpleNamespace

import pytest

from services.inference.models import InferenceError, InferencePolicy, InferenceRequest
from services.inference.providers import gemini_provider as gemini_provider_module
from services.inference.providers import key_pool as key_pool_module
from services.inference.providers.gemini_provider import GeminiProvider
from services.inference.providers.key_pool import GeminiKeyPool, reset_key_pool


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_key_pool()
    yield
    reset_key_pool()


# --- test doubles -------------------------------------------------------------

class FakeAPIError(Exception):
    """Mimics google.genai.errors.APIError: carries an int `code`."""

    def __init__(self, code, message=""):
        super().__init__(message or f"{code} error")
        self.code = code


class FakeModels:
    def __init__(self, *, text=None, exc=None, captured=None):
        self._text = text
        self._exc = exc
        self._captured = captured

    def generate_content(self, *, model, contents, config=None):
        if self._captured is not None:
            self._captured.update(model=model, contents=contents, config=config)
        if self._exc is not None:
            raise self._exc
        return SimpleNamespace(text=self._text)


class FakeClient:
    def __init__(self, *, text=None, exc=None, captured=None):
        self.models = FakeModels(text=text, exc=exc, captured=captured)


def _pool(client_map, **kwargs):
    """client_map: {key_id: FakeClient}. Keys ordered by insertion."""
    keys = list(client_map.keys())
    return GeminiKeyPool(keys, client_factory=lambda k: client_map[k], **kwargs)


def _request(output_mode="json", agent="resolution_agent"):
    return InferenceRequest(
        agent_name=agent,
        task_type="t",
        system_prompt="sys",
        user_prompt="usr",
        output_mode=output_mode,
        temperature=0.25,
    )


def _policy(agent="resolution_agent", model="gemini-2.5-flash-lite"):
    return InferencePolicy(agent_name=agent, primary_model=model)


# --- single-key behavior (parity with old provider) ---------------------------

def test_valid_json_parses():
    pool = _pool({"k1": FakeClient(text='{"confidence": "high"}')})
    provider = GeminiProvider(pool=pool)
    result = provider.generate(_request(), _policy())
    assert result.failure_type is None
    assert result.parsed_data == {"confidence": "high"}


def test_malformed_json_returns_structure_failure():
    pool = _pool({"k1": FakeClient(text="not json{")})
    provider = GeminiProvider(pool=pool)
    result = provider.generate(_request(), _policy())
    assert result.failure_type == "STRUCTURE_FAILURE"
    assert result.parsed_data is None


def test_empty_text_returns_structure_failure():
    pool = _pool({"k1": FakeClient(text="")})
    provider = GeminiProvider(pool=pool)
    result = provider.generate(_request(), _policy())
    assert result.failure_type == "STRUCTURE_FAILURE"


def test_free_text_mode_skips_json_parsing():
    captured = {}
    pool = _pool({"k1": FakeClient(text="hello", captured=captured)})
    provider = GeminiProvider(pool=pool)
    result = provider.generate(_request(output_mode="free_text"), _policy())
    assert result.parsed_data is None
    assert result.content == "hello"
    assert captured["config"].response_mime_type is None


def test_json_mode_requests_json_mime_type_and_passes_prompt():
    captured = {}
    pool = _pool({"k1": FakeClient(text='{"ok": true}', captured=captured)})
    provider = GeminiProvider(pool=pool)
    provider.generate(_request(), _policy(model="gemini-2.5-flash-lite"))
    assert captured["model"] == "gemini-2.5-flash-lite"
    assert captured["contents"] == "usr"
    assert captured["config"].response_mime_type == "application/json"
    assert captured["config"].system_instruction == "sys"
    assert captured["config"].temperature == 0.25


# --- failover -----------------------------------------------------------------

def test_rotates_to_next_key_on_429():
    pool = _pool({
        "k1": FakeClient(exc=FakeAPIError(429, "quota")),
        "k2": FakeClient(text='{"ok": true}'),
    })
    provider = GeminiProvider(pool=pool)
    result = provider.generate(_request(), _policy())
    assert result.parsed_data == {"ok": True}
    # k1 was penalized → next acquire skips it and returns k2.
    assert pool.acquire().key_id == "k2"


def test_raises_when_all_keys_rate_limited():
    pool = _pool({
        "k1": FakeClient(exc=FakeAPIError(429)),
        "k2": FakeClient(exc=FakeAPIError(429)),
    })
    provider = GeminiProvider(pool=pool)
    with pytest.raises(InferenceError, match="exhausted or cooling down"):
        provider.generate(_request(), _policy())
    assert pool.acquire() is None  # both penalized


def test_non_rotatable_error_raises_without_trying_other_keys():
    k2 = FakeClient(text='{"ok": true}')
    pool = _pool({
        "k1": FakeClient(exc=ValueError("network down")),
        "k2": k2,
    })
    provider = GeminiProvider(pool=pool)
    with pytest.raises(InferenceError):
        provider.generate(_request(), _policy())
    # k2 must NOT have been consumed by generate(): it is still first healthy.
    assert pool.acquire().key_id == "k1"


def test_rotates_on_auth_and_server_errors():
    pool = _pool({
        "k1": FakeClient(exc=FakeAPIError(403, "permission denied")),
        "k2": FakeClient(exc=FakeAPIError(503, "unavailable")),
        "k3": FakeClient(text='{"ok": true}'),
    })
    provider = GeminiProvider(pool=pool)
    result = provider.generate(_request(), _policy())
    assert result.parsed_data == {"ok": True}


# --- availability / construction ----------------------------------------------

def test_is_available_reflects_pool():
    assert GeminiProvider(pool=_pool({"k1": FakeClient(text="x")})).is_available() is True
    empty = GeminiKeyPool([], client_factory=lambda k: k)
    assert GeminiProvider(pool=empty).is_available() is False


def test_no_keys_raises_inference_error():
    provider = GeminiProvider(pool=GeminiKeyPool([], client_factory=lambda k: k))
    with pytest.raises(InferenceError, match="not configured"):
        provider.generate(_request(), _policy())


def test_api_key_constructor_builds_single_key_pool(monkeypatch):
    captured = {}

    class _SDKClient:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key
            self.models = FakeModels(text='{"ok": true}', captured=captured)

    monkeypatch.setattr(key_pool_module.genai, "Client", _SDKClient)

    provider = GeminiProvider(api_key="legacy-key")
    result = provider.generate(_request(), _policy())
    assert captured["api_key"] == "legacy-key"
    assert result.parsed_data == {"ok": True}


def test_default_constructor_uses_env_singleton(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    reset_key_pool()
    provider = GeminiProvider()
    assert provider.is_available() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/services/inference/test_gemini_provider.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'pool'` (old provider has no `pool` param)

- [ ] **Step 3: Rewrite the provider**

Replace the entire contents of `services/inference/providers/gemini_provider.py`:

```python
import json

from google.genai import types

from services.inference.models import InferenceError, InferenceResult
from services.inference.providers.gemini_errors import (
    is_rotatable_error,
    parse_retry_delay,
)
from services.inference.providers.key_pool import GeminiKeyPool, get_key_pool


class GeminiProvider:
    provider_name = "gemini"

    def __init__(self, api_key: str | None = None, *, pool=None, client_factory=None):
        if pool is not None:
            self._pool = pool
        elif api_key is not None:
            kwargs = {"client_factory": client_factory} if client_factory else {}
            self._pool = GeminiKeyPool([api_key], **kwargs)
        else:
            self._pool = get_key_pool()

    def is_available(self) -> bool:
        return self._pool.has_keys()

    def generate(self, request, policy):
        if not self._pool.has_keys():
            raise InferenceError("GEMINI_API_KEY is not configured")

        last_exc = None
        for _ in range(self._pool.num_keys()):
            handle = self._pool.acquire()
            if handle is None:  # every key is cooling down
                break
            try:
                response = self._call(handle.client, request, policy)
            except Exception as exc:  # noqa: BLE001 - classify below
                if is_rotatable_error(exc):
                    # Key-specific failure (429/auth/5xx): cool it down and try
                    # the next healthy key with this same request.
                    self._pool.penalize(handle.key_id, parse_retry_delay(exc))
                    last_exc = exc
                    continue
                # Not key-specific (network, 4xx input): switching keys won't help.
                raise InferenceError(
                    f"Gemini API call failed for agent={request.agent_name} "
                    f"model={policy.primary_model}: {exc!r}"
                ) from exc
            return self._build_result(response, request, policy)

        raise InferenceError(
            f"All Gemini API keys exhausted or cooling down for "
            f"agent={request.agent_name} model={policy.primary_model}: {last_exc!r}"
        )

    @staticmethod
    def _call(client, request, policy):
        json_mode = request.output_mode == "json"
        return client.models.generate_content(
            model=policy.primary_model,
            contents=request.user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=request.system_prompt,
                temperature=request.temperature,
                response_mime_type="application/json" if json_mode else None,
            ),
        )

    def _build_result(self, response, request, policy):
        text = (getattr(response, "text", "") or "").strip()

        def _result(**kwargs):
            return InferenceResult(
                agent_name=request.agent_name,
                model=policy.primary_model,
                provider=self.provider_name,
                content=text,
                **kwargs,
            )

        if request.output_mode != "json":
            return _result()
        if not text:
            return _result(failure_type="STRUCTURE_FAILURE")
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return _result(failure_type="STRUCTURE_FAILURE")
        return _result(parsed_data=parsed)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/services/inference/test_gemini_provider.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Stage changes (do NOT commit)**

```bash
git add services/inference/providers/gemini_provider.py tests/services/inference/test_gemini_provider.py
```

---

## Task 5: Full regression + manual verification

**Files:** none (verification only), then spec status bump.

- [ ] **Step 1: Run the full inference + factory + boundary suites**

Run:
```bash
./.venv/Scripts/python.exe -m pytest tests/services/inference tests/ingestion/test_inference_boundaries.py tests/ingestion/test_settings_env.py -v
```
Expected: PASS, no failures. (`test_factory.py` still green — gateway/registry unchanged.)

- [ ] **Step 2: Run the broader service suite for regressions**

Run:
```bash
./.venv/Scripts/python.exe -m pytest tests/services tests/agents -q
```
Expected: PASS (no regressions in profile/intent/conversation/conflict paths that call the gateway).

- [ ] **Step 3: Manual smoke — multi-key failover with fakes (no network)**

Run:
```bash
./.venv/Scripts/python.exe -c "from services.inference.providers.key_pool import GeminiKeyPool; from services.inference.providers.gemini_provider import GeminiProvider; from services.inference.models import InferenceRequest, InferencePolicy; class E(Exception):\n  def __init__(s):\n    super().__init__('429 quota'); s.code=429
class M:\n  def __init__(s,t=None,e=None): s._t=t; s._e=e\n  def generate_content(s,**k):\n    if s._e: raise s._e\n    import types as _t; return _t.SimpleNamespace(text=s._t)
class C:\n  def __init__(s,t=None,e=None): s.models=M(t,e)
cm={'k1':C(e=E()),'k2':C(t='{\"ok\":true}')}
p=GeminiKeyPool(list(cm),client_factory=lambda k:cm[k])
pr=GeminiProvider(pool=p)
r=pr.generate(InferenceRequest(agent_name='a',task_type='t',system_prompt='s',user_prompt='u',output_mode='json'), InferencePolicy(agent_name='a',primary_model='m'))
print('result:', r.parsed_data, '| next key after k1 penalized:', p.acquire().key_id)"
```
Expected output: `result: {'ok': True} | next key after k1 penalized: k2`

- [ ] **Step 4: Update the spec status**

Edit `docs/superpowers/specs/2026-05-31-gemini-api-key-rotation-design.md`: change `**Status:** Draft` → `**Status:** Implemented`.

- [ ] **Step 5: Stage changes (do NOT commit)**

```bash
git add docs/superpowers/specs/2026-05-31-gemini-api-key-rotation-design.md
```

---

## How the user enables it

In `.env`:
```
GEMINI_API_KEYS=key_one,key_two,key_three
```
(Keep or drop `GEMINI_API_KEY`; both are merged.) Restart uvicorn. When `key_one`
hits 429, the rotator parses its `retryDelay`, cools `key_one` down, and retries
the same request on `key_two` — transparently to every gateway call site.

---

## Definition of done (Plan 3)

- [ ] `GeminiProvider.generate()` xoay key qua pool; lỗi rotatable → penalize + thử key kế; lỗi không-rotatable → raise ngay; hết key → `InferenceError`. 14 test xanh.
- [ ] Backward-compat: `GeminiProvider(api_key="x")` dựng pool 1-key; constructor mặc định dùng singleton env.
- [ ] Regression đầy đủ (`tests/services`, `tests/agents`) xanh; smoke thủ công in đúng output.
- [ ] Spec status đổi sang `Implemented`. Tất cả thay đổi đã `git add` (chưa commit).
