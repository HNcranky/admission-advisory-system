import observability.prompts as prompts
from services.knowledge.qa_service import KNOWLEDGE_QA_SYSTEM_PROMPT, KnowledgeQAService
from services.inference.models import InferenceResult


class _CapturingGateway:
    def __init__(self):
        self.request = None

    def run(self, request):
        self.request = request
        # empty answer => _generate returns no-data without touching citations
        return InferenceResult(
            agent_name=request.agent_name, model="m", provider="fake",
            content='{"answer": ""}', parsed_data={"answer": ""},
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
    handle = _FakePrompt("LANGFUSE QA PROMPT")
    monkeypatch.setattr(prompts, "get_langfuse", lambda: _FakeLangfuse(handle))
    gw = _CapturingGateway()
    svc = KnowledgeQAService(chunk_repository=object(), embedder=object(), gateway=gw)
    svc._generate(question="học phí?", chunks=[], confidence=0.9, conversation_context="")
    assert gw.request.system_prompt == "LANGFUSE QA PROMPT"
    assert gw.request.prompt is handle


# PIN test: with Langfuse off, behaviour is byte-identical to today.
def test_system_prompt_matches_constant_when_langfuse_disabled(monkeypatch):
    monkeypatch.setattr(prompts, "get_langfuse", lambda: None)
    gw = _CapturingGateway()
    svc = KnowledgeQAService(chunk_repository=object(), embedder=object(), gateway=gw)
    svc._generate(question="học phí?", chunks=[], confidence=0.9, conversation_context="")
    assert gw.request.system_prompt == KNOWLEDGE_QA_SYSTEM_PROMPT
    assert gw.request.prompt is None
