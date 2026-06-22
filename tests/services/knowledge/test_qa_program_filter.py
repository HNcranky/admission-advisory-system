from services.knowledge.models import ScoredChunk
from services.knowledge.qa_service import KnowledgeQAService


class FakeEmbedder:
    def embed(self, texts, task_type=None):
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeChunkRepo:
    def __init__(self):
        self.calls = []          # list of program kwargs seen by vector_search

    def resolve_program(self, question, school=None):
        return "Kỹ thuật Ô tô" if "Ô tô" in (question or "") else None

    def vector_search(self, embedding, school=None, topic=None,
                      program=None, limit=5):
        self.calls.append({"school": school, "topic": topic, "program": program})
        return []                # empty -> gate goes to no_data (no LLM needed)


def _service(repo):
    # gateway=object(): never invoked because empty chunks short-circuit to no_data.
    return KnowledgeQAService(
        chunk_repository=repo, embedder=FakeEmbedder(),
        gateway=object(), cache=None,
    )


def test_retrieve_method_forwards_resolved_program():
    repo = FakeChunkRepo()
    svc = _service(repo)
    svc.retrieve("cơ hội việc làm ngành Kỹ thuật Ô tô", "HUST", "program_overview")
    school_call = repo.calls[0]
    assert school_call["program"] == "Kỹ thuật Ô tô"


def test_graph_retrieve_node_forwards_program():
    repo = FakeChunkRepo()
    svc = _service(repo)
    svc.answer("cơ hội việc làm ngành Kỹ thuật Ô tô", "HUST", "program_overview")
    # First (school-scoped) call carries the resolved program...
    assert repo.calls[0]["school"] == "HUST"
    assert repo.calls[0]["program"] == "Kỹ thuật Ô tô"
    # ...the national-scope augmentation call must NOT filter by program.
    national = [c for c in repo.calls if c["school"] != "HUST"]
    assert national and all(c["program"] is None for c in national)


def test_non_program_question_uses_no_filter():
    repo = FakeChunkRepo()
    svc = _service(repo)
    svc.retrieve("phương thức xét tuyển", "HUST", "admission_policy")
    assert repo.calls[0]["program"] is None
