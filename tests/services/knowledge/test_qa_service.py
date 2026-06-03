from services.inference.models import InferenceError, InferenceResult
from services.knowledge.models import ScoredChunk
from services.knowledge.qa_service import KnowledgeQAService


class FakeEmbedder:
    def __init__(self, vector=None):
        self.calls = []
        self._vector = vector or [0.1, 0.2, 0.3]

    def embed(self, texts, task_type="RETRIEVAL_DOCUMENT"):
        self.calls.append({"texts": list(texts), "task_type": task_type})
        return [list(self._vector) for _ in texts]


class FakeChunkRepo:
    def __init__(self, chunks):
        self._chunks = chunks
        self.calls = []

    def vector_search(self, embedding, school=None, topic=None, limit=5):
        self.calls.append(
            {"embedding": embedding, "school": school, "topic": topic, "limit": limit}
        )
        return list(self._chunks)


class FakeGateway:
    def __init__(self, parsed_data=None, raise_exc=False):
        self.calls = []
        self._parsed = parsed_data
        self._raise = raise_exc

    def run(self, request):
        self.calls.append(request)
        if self._raise:
            raise InferenceError("simulated generation failure")
        return InferenceResult(
            agent_name=request.agent_name,
            model="test-model",
            provider="test",
            content="{}",
            parsed_data=self._parsed,
        )


def _chunk(text, url, score, school="VNU-UET", topic="tuition"):
    return ScoredChunk(
        school=school, topic=topic, chunk_text=text, source_url=url, score=score
    )


def _build(chunks, parsed_data=None, raise_exc=False, vector=None, min_score=0.5, top_k=5):
    embedder = FakeEmbedder(vector=vector)
    repo = FakeChunkRepo(chunks)
    gateway = FakeGateway(parsed_data=parsed_data, raise_exc=raise_exc)
    service = KnowledgeQAService(
        chunk_repository=repo,
        embedder=embedder,
        gateway=gateway,
        min_score=min_score,
        top_k=top_k,
    )
    return service, embedder, repo, gateway


# ─── threshold gate ──────────────────────────────────────────────────────────

def test_no_chunks_returns_no_data_without_calling_gateway():
    service, _, _, gateway = _build([])
    res = service.answer("học phí bao nhiêu", school="VNU-UET", topic="tuition")
    assert res.has_data is False
    assert res.answer is None
    assert res.confidence == 0.0
    assert gateway.calls == []


def test_below_threshold_returns_no_data_without_calling_gateway():
    chunks = [_chunk("Học phí 35 triệu", "http://uet/a", score=0.3)]
    service, _, _, gateway = _build(chunks, parsed_data={"answer": "x"}, min_score=0.5)
    res = service.answer("học phí bao nhiêu", "VNU-UET", "tuition")
    assert res.has_data is False
    assert res.confidence == 0.3
    assert gateway.calls == []


# ─── embedding + retrieval wiring ────────────────────────────────────────────

def test_query_embedded_with_retrieval_query_task_type():
    chunks = [_chunk("Học phí 35 triệu", "http://uet/a", score=0.9)]
    service, embedder, _, _ = _build(
        chunks, parsed_data={"answer": "Học phí 35 triệu/năm."}
    )
    service.answer("học phí bao nhiêu", "VNU-UET", "tuition")
    assert embedder.calls[0]["texts"] == ["học phí bao nhiêu"]
    assert embedder.calls[0]["task_type"] == "RETRIEVAL_QUERY"


def test_metadata_filters_passed_to_vector_search():
    chunks = [_chunk("x", "u", score=0.9)]
    service, _, repo, _ = _build(chunks, parsed_data={"answer": "ok"}, top_k=5)
    service.answer("q", "VNU-UET", "tuition")
    assert repo.calls[0]["school"] == "VNU-UET"
    assert repo.calls[0]["topic"] == "tuition"
    assert repo.calls[0]["limit"] == 5


# ─── basic generation (citations refined in Task 2) ──────────────────────────

def test_above_threshold_returns_grounded_answer_with_confidence():
    chunks = [
        _chunk("Học phí 35 triệu/năm", "http://uet/a", score=0.92),
        _chunk("Thông tin khác", "http://uet/b", score=0.71),
    ]
    service, _, _, gateway = _build(
        chunks, parsed_data={"answer": "Học phí khoảng 35 triệu/năm."}
    )
    res = service.answer("học phí bao nhiêu", "VNU-UET", "tuition")
    assert res.has_data is True
    assert res.answer == "Học phí khoảng 35 triệu/năm."
    assert res.confidence == 0.92
    assert len(gateway.calls) == 1
    # No used_source_ids in the response → cite every passed chunk.
    assert len(res.citations) == 2


def test_citations_limited_to_used_source_ids():
    chunks = [
        _chunk("Học phí 35 triệu/năm", "http://uet/a", score=0.92),
        _chunk("Ký túc xá", "http://uet/b", score=0.71),
    ]
    service, _, _, _ = _build(
        chunks, parsed_data={"answer": "Học phí 35 triệu.", "used_source_ids": [1]}
    )
    res = service.answer("học phí bao nhiêu", "VNU-UET", "tuition")
    assert len(res.citations) == 1
    assert res.citations[0].source_url == "http://uet/a"
    assert res.citations[0].chunk_text == "Học phí 35 triệu/năm"


def test_citations_fallback_to_all_chunks_when_used_ids_empty():
    chunks = [_chunk("a", "http://uet/a", 0.9), _chunk("b", "http://uet/b", 0.8)]
    service, _, _, _ = _build(
        chunks, parsed_data={"answer": "ans", "used_source_ids": []}
    )
    res = service.answer("q", "VNU-UET", "tuition")
    assert len(res.citations) == 2


def test_citations_fallback_when_used_ids_invalid():
    chunks = [_chunk("a", "http://uet/a", 0.9)]
    service, _, _, _ = _build(
        chunks, parsed_data={"answer": "ans", "used_source_ids": [99, "x"]}
    )
    res = service.answer("q", "VNU-UET", "tuition")
    assert len(res.citations) == 1
    assert res.citations[0].source_url == "http://uet/a"


def test_citations_deduped_by_source_url():
    chunks = [
        _chunk("đoạn 1", "http://uet/same", 0.9),
        _chunk("đoạn 2", "http://uet/same", 0.8),
    ]
    service, _, _, _ = _build(
        chunks, parsed_data={"answer": "ans", "used_source_ids": [1, 2]}
    )
    res = service.answer("q", "VNU-UET", "tuition")
    assert len(res.citations) == 1
    assert res.citations[0].source_url == "http://uet/same"


def test_no_answer_text_degrades_to_no_data():
    chunks = [_chunk("Học phí 35 triệu", "http://uet/a", 0.92)]
    service, _, _, _ = _build(chunks, parsed_data=None)  # JSON structure failure
    res = service.answer("q", "VNU-UET", "tuition")
    assert res.has_data is False
    assert res.answer is None
    assert res.confidence == 0.92


def test_empty_answer_string_degrades_to_no_data():
    chunks = [_chunk("x", "http://uet/a", 0.92)]
    service, _, _, _ = _build(
        chunks, parsed_data={"answer": "   ", "used_source_ids": [1]}
    )
    res = service.answer("q", "VNU-UET", "tuition")
    assert res.has_data is False


def test_gateway_exception_degrades_to_no_data():
    chunks = [_chunk("x", "http://uet/a", 0.92)]
    service, _, _, gateway = _build(chunks, raise_exc=True)
    res = service.answer("q", "VNU-UET", "tuition")
    assert res.has_data is False
    assert len(gateway.calls) == 1
