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
