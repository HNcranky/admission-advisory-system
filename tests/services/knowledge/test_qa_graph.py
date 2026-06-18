from services.knowledge.models import ScoredChunk
from services.knowledge.qa_service import KnowledgeQAService


class _FakeEmbedder:
    def embed(self, texts, task_type=None):
        return [[0.1, 0.2, 0.3] for _ in texts]


class _FakeRepo:
    def __init__(self, chunks):
        self._chunks = chunks
        self.calls = []

    def vector_search(self, embedding, school, topic, limit):
        self.calls.append((school, topic, limit))
        return list(self._chunks)


class _FakeGateway:
    def __init__(self, answer="Học phí 15 triệu/năm."):
        self._answer = answer

    def run(self, request):
        class R: parsed_data = {"answer": self._answer, "used_source_ids": [1]}
        return R()


def _chunk(text, score, url="http://u"):
    return ScoredChunk(school="UET", topic="tuition", chunk_text=text, source_url=url, score=score)


def _service(chunks, min_score=0.2, answer="Học phí 15 triệu/năm."):
    return KnowledgeQAService(
        chunk_repository=_FakeRepo(chunks),
        embedder=_FakeEmbedder(),
        gateway=_FakeGateway(answer),
        min_score=min_score,
        cache_enabled=False,
    )


def test_graph_generates_when_above_min_score():
    svc = _service([_chunk("học phí 15tr", 0.9)])
    result = svc.answer(question="học phí UET?", school="UET", topic="tuition")
    assert result.has_data is True
    assert "15 triệu" in result.answer
    assert result.confidence == 0.9
    assert result.citations and result.citations[0].source_url == "http://u"


def test_graph_no_data_below_min_score():
    svc = _service([_chunk("noise", 0.05)], min_score=0.2)
    result = svc.answer(question="học phí UET?", school="UET", topic="tuition")
    assert result.has_data is False
    assert result.confidence == 0.05


def test_graph_no_data_when_no_chunks():
    svc = _service([])
    result = svc.answer(question="học phí UET?", school="UET", topic="tuition")
    assert result.has_data is False


def test_injected_national_is_not_refetched():
    # National-scope school is None → augment is a no-op; ensure injection path runs clean.
    svc = _service([_chunk("x", 0.9)])
    result = svc.answer(question="q", school="UET", topic="tuition",
                        query_vector=[0.5, 0.5, 0.5], national=[])
    # With national=[] injected and school-scoped, _augment_with_national merges [] → chunks unchanged.
    assert result.has_data is True


def test_build_kqa_graph_direct_invoke():
    from services.knowledge.qa_graph import KQAState, build_kqa_graph
    svc = _service([_chunk("học phí 15tr", 0.9)])
    graph = build_kqa_graph(svc)
    final = graph.invoke(KQAState(question="q", school="UET", topic="tuition"))
    result = final["result"] if isinstance(final, dict) else final.result
    assert result.has_data is True and result.confidence == 0.9
