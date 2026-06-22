from services.knowledge.models import ScoredChunk
from services.knowledge.qa_service import KnowledgeQAService


class _FakeEmbedder:
    def embed(self, texts, task_type=None):
        return [[0.1, 0.2, 0.3] for _ in texts]


class _FakeRepo:
    def __init__(self):
        self.calls = []

    def resolve_program(self, question, school=None):
        return None

    def vector_search(self, embedding, school=None, topic=None, program=None, limit=None):
        self.calls.append((school, topic))
        return [ScoredChunk(chunk_text=f"{school}:{topic}", score=0.7, school=school or "x")]


def test_retrieve_embeds_once_and_returns_chunks():
    repo = _FakeRepo()
    svc = KnowledgeQAService(chunk_repository=repo, embedder=_FakeEmbedder(), gateway=object())

    chunks = svc.retrieve("Chỉ tiêu?", school="hust", topic="quota")

    assert chunks and isinstance(chunks[0], ScoredChunk)
    assert ("hust", "quota") in repo.calls
