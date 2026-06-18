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
