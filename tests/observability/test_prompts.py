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
