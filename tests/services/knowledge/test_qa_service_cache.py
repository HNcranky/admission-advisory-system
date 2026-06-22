from services.inference.models import InferenceResult
from services.knowledge.models import Citation, KnowledgeQAResult, ScoredChunk
from services.knowledge.qa_cache import CachedAnswer
from services.knowledge.qa_service import KnowledgeQAService


class FakeEmbedder:
    def __init__(self):
        self.calls = 0

    def embed(self, texts, task_type="RETRIEVAL_DOCUMENT"):
        self.calls += 1
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeChunkRepo:
    def __init__(self, chunks):
        self._chunks = chunks

    def resolve_program(self, question, school=None):
        return None

    def vector_search(self, embedding, school=None, topic=None, program=None, limit=5):
        return list(self._chunks)


class FakeGateway:
    def __init__(self, parsed_data=None):
        self.calls = []
        self._parsed = parsed_data

    def run(self, request):
        self.calls.append(request)
        return InferenceResult(
            agent_name=request.agent_name, model="test-model",
            provider="test", content="{}", parsed_data=self._parsed,
        )


class FakeCache:
    def __init__(self, hit=None, lookup_raises=False):
        self._hit = hit
        self._lookup_raises = lookup_raises
        self.lookups = []
        self.stores = []

    def lookup(self, embedding, school, topic, threshold):
        self.lookups.append((list(embedding), school, topic, threshold))
        if self._lookup_raises:
            raise RuntimeError("boom")
        return self._hit

    def scope_keys(self, school, topic):
        return [f"s:{school}|t:{topic}", f"s:{school}|t:*"]

    def current_versions(self, keys):
        return {k: 1 for k in keys}

    def store(self, school, topic, question, embedding, result, dep_versions, ttl_days):
        self.stores.append({
            "school": school, "topic": topic, "question": question,
            "result": result, "dep_versions": dep_versions, "ttl_days": ttl_days,
        })


def _chunk(text, url, score):
    return ScoredChunk(school="HUST", topic="tuition", chunk_text=text,
                       source_url=url, score=score)


def _service(chunks, cache, parsed_data=None):
    return KnowledgeQAService(
        chunk_repository=FakeChunkRepo(chunks),
        embedder=FakeEmbedder(),
        gateway=FakeGateway(parsed_data=parsed_data),
        min_score=0.5, top_k=5, cache=cache,
    )


def test_cache_hit_returns_cached_answer_without_generation():
    cache = FakeCache(hit=CachedAnswer(
        answer="cached fee", citations=[Citation(source_url="u", chunk_text="t")],
        confidence=0.9,
    ))
    svc = _service([_chunk("x", "u", 0.92)], cache, parsed_data={"answer": "fresh"})
    res = svc.answer("học phí?", school="HUST", topic="tuition")

    assert res.from_cache is True
    assert res.answer == "cached fee"
    assert svc._gateway.calls == []          # generation skipped on hit
    assert cache.stores == []                # nothing stored on a hit


def test_cache_miss_generates_then_stores():
    cache = FakeCache(hit=None)
    svc = _service([_chunk("Học phí 35tr", "u", 0.92)], cache,
                   parsed_data={"answer": "Học phí 35 triệu.", "used_source_ids": [1]})
    res = svc.answer("học phí?", school="HUST", topic="tuition")

    assert res.from_cache is False
    assert res.has_data is True
    assert len(svc._gateway.calls) == 1
    assert len(cache.stores) == 1
    assert cache.stores[0]["result"].answer == "Học phí 35 triệu."
    assert cache.stores[0]["dep_versions"] == {"s:HUST|t:tuition": 1, "s:HUST|t:*": 1}
    assert cache.stores[0]["ttl_days"] == 30


def test_below_threshold_miss_does_not_store_or_generate():
    cache = FakeCache(hit=None)
    svc = _service([_chunk("weak", "u", 0.3)], cache, parsed_data={"answer": "x"})
    res = svc.answer("học phí?", school="HUST", topic="tuition")

    assert res.has_data is False
    assert svc._gateway.calls == []          # KQA gate blocks generation
    assert cache.stores == []                # thin docs → not cached


def test_no_data_answer_is_not_stored():
    cache = FakeCache(hit=None)
    svc = _service([_chunk("Học phí 35tr", "u", 0.92)], cache, parsed_data=None)
    res = svc.answer("học phí?", school="HUST", topic="tuition")

    assert res.has_data is False
    assert len(svc._gateway.calls) == 1      # generation attempted...
    assert cache.stores == []                # ...but produced no grounded answer


def test_school_none_bypasses_cache():
    cache = FakeCache(hit=CachedAnswer(answer="should not be used", citations=[], confidence=0.9))
    svc = _service([_chunk("x", "u", 0.92)], cache, parsed_data={"answer": "ok"})
    res = svc.answer("q", school=None, topic="tuition")

    assert cache.lookups == []
    assert cache.stores == []
    assert res.from_cache is False


def test_topic_none_bypasses_cache():
    cache = FakeCache(hit=CachedAnswer(answer="nope", citations=[], confidence=0.9))
    svc = _service([_chunk("x", "u", 0.92)], cache, parsed_data={"answer": "ok"})
    svc.answer("q", school="HUST", topic=None)

    assert cache.lookups == []
    assert cache.stores == []


def test_lookup_failure_degrades_to_generation():
    cache = FakeCache(lookup_raises=True)
    svc = _service([_chunk("Học phí 35tr", "u", 0.92)], cache,
                   parsed_data={"answer": "Học phí 35 triệu.", "used_source_ids": [1]})
    res = svc.answer("học phí?", school="HUST", topic="tuition")

    assert res.has_data is True              # fell through to the graph
    assert len(svc._gateway.calls) == 1


def test_supplied_query_vector_used_for_lookup_without_embedding():
    cache = FakeCache(hit=CachedAnswer(answer="cached", citations=[], confidence=0.9))
    svc = _service([], cache)
    svc.answer("q", school="HUST", topic="tuition", query_vector=[0.7, 0.8, 0.9])

    assert svc._embedder.calls == 0                       # supplied vector reused
    assert cache.lookups[0][0] == [0.7, 0.8, 0.9]         # lookup used that vector
