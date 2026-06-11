import eval.knowledge_qa.runner as runner
from eval.knowledge_qa.models import GoldenCase, GoldenChunk
from services.knowledge.models import KnowledgeQAResult


class _FakeService:
    def __init__(self):
        self.seen = None

    def generate_from_chunks(self, question, chunks, conversation_context=""):
        self.seen = (question, chunks)
        return KnowledgeQAResult(has_data=True, answer="ok", confidence=chunks[0].score)


def test_run_case_feeds_frozen_chunks_to_forced_model(monkeypatch):
    fake = _FakeService()
    captured = {}

    def fake_service_for(model):
        captured["model"] = model
        return fake

    monkeypatch.setattr(runner, "_service_for", fake_service_for)

    case = GoldenCase(
        id="c1", question="Chỉ tiêu?", school="hust", topic="quota",
        chunks=[GoldenChunk(chunk_text="A 300", score=0.8, school="hust")],
    )

    result = runner.run_case(case, "gemini-2.5-flash-lite")

    assert result.answer == "ok"
    assert captured["model"] == "gemini-2.5-flash-lite"
    assert fake.seen[0] == "Chỉ tiêu?"
    assert fake.seen[1][0].score == 0.8   # ScoredChunk reconstructed from frozen chunk
