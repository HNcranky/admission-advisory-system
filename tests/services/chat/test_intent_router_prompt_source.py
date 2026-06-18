import observability.prompts as prompts
from services.chat.intent_router import INTENT_SYSTEM_PROMPT, IntentRouter
from services.chat.models import ChatProfileState
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
