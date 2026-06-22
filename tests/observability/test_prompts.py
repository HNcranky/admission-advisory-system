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


def test_get_prompt_service_is_singleton():
    from observability.prompts import get_prompt_service
    assert get_prompt_service() is get_prompt_service()
    assert isinstance(get_prompt_service(), PromptService)
