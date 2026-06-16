from services.inference.models import InferenceResult
from services.knowledge.models import ScoredChunk
from services.knowledge.qa_service import KnowledgeQAService


class _FakeGateway:
    def __init__(self, parsed):
        self._parsed = parsed

    def run(self, request):
        return InferenceResult(
            agent_name="knowledge_qa_agent", model="m", provider="fake",
            content="{}", parsed_data=self._parsed,
        )


def _chunk(text, score, url="https://x"):
    return ScoredChunk(chunk_text=text, score=score, school="hust", source_url=url)


def test_generate_from_chunks_returns_grounded_answer():
    gw = _FakeGateway({"answer": "Chỉ tiêu là 300.", "used_source_ids": [1]})
    svc = KnowledgeQAService(chunk_repository=object(), embedder=object(), gateway=gw)

    out = svc.generate_from_chunks("Chỉ tiêu?", [_chunk("A 300", 0.8), _chunk("B 25tr", 0.6)])

    assert out.has_data is True
    assert out.answer == "Chỉ tiêu là 300."
    assert out.confidence == 0.8
    assert out.citations[0].chunk_text == "A 300"


def test_generate_from_chunks_empty_chunks_is_no_data():
    gw = _FakeGateway({"answer": "x"})
    svc = KnowledgeQAService(chunk_repository=object(), embedder=object(), gateway=gw)

    out = svc.generate_from_chunks("Chỉ tiêu?", [])

    assert out.has_data is False
