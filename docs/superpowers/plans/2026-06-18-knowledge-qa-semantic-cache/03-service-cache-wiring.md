# Knowledge QA Cache — Plan 03: Service Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire `QACacheRepository` into `KnowledgeQAService.answer()` — cache lookup before generation, conditional store after — enabled by default in production, fully degrade-gracefully, with zero behaviour change to the existing graph path.

**Architecture:** `answer()` keeps its existing graph invocation extracted into `_run_graph(...)`. When the cache is active and the call has a concrete `(school, topic)`, `answer()` computes the query embedding once (reusing a supplied `query_vector`), tries `cache.lookup`, and on a hit returns `hit.to_result(from_cache=True)`. On a miss it runs the graph **with the same embedding passed as `query_vector`** (the graph's embed node reuses it — no second embedding call), then stores the result only if it cleared the quality gate (`has_data and confidence >= min_score`). Every cache call is wrapped so any fault logs a warning and falls through to normal generation.

**Tech Stack:** Python 3.12, LangGraph (existing KQA subgraph), pytest.

## Global Constraints

- **Never run `git push`.** No `Co-Authored-By` / AI attribution in commits.
- LLM/cache call sites must **degrade gracefully**: wrap `cache.lookup`/`cache.store`, `logger.warning` on failure, never break QA.
- Pydantic **v2**.
- The production service is constructed no-arg (`KnowledgeQAService()` in `services/chat/conversation_service.py:56` and `services/chat/compare_orchestrator.py:14`), so the cache must be **enabled by default**. Existing unit tests build the service with explicit fakes and must opt out via `cache_enabled=False`.
- **Depends on Plan 01 + Plan 02** (`QACacheRepository` with `scope_keys`, `current_versions`, `store`, `lookup`; `CachedAnswer`; `KnowledgeQAResult.from_cache`; settings `KNOWLEDGE_QA_CACHE_ENABLED/THRESHOLD/TTL_DAYS`).
- Run tests with `python -m pytest -q` (system Python 3.12).

---

### Task 1: Constructor cache wiring + `_run_graph` extraction

**Files:**
- Modify: `services/knowledge/qa_service.py` (imports ~line 4, `__init__` ~line 33, `answer` ~line 56)

**Interfaces:**
- Consumes: `QACacheRepository`, `CachedAnswer`, settings `KNOWLEDGE_QA_CACHE_*`.
- Produces:
  - `KnowledgeQAService(__init__)` gains `cache=None, cache_enabled: bool = KNOWLEDGE_QA_CACHE_ENABLED, cache_threshold: float = KNOWLEDGE_QA_CACHE_THRESHOLD, cache_ttl_days: int = KNOWLEDGE_QA_CACHE_TTL_DAYS`. Resolution: explicit `cache` wins; else auto-create `QACacheRepository()` when `cache_enabled`; else `self._cache = None` (disabled).
  - `KnowledgeQAService._run_graph(question, school, topic, conversation_context, query_vector, national, retrieval_query) -> KnowledgeQAResult` (the former `answer()` body, behaviour-identical).

This task only refactors/extends; behaviour is verified unchanged by the existing suite. (No new test here — Task 3 adds behaviour tests; this task must keep the existing suite green.)

- [ ] **Step 1: Extend the settings import**

In `services/knowledge/qa_service.py`, change:

```python
from ingestion.config.settings import (
    KNOWLEDGE_QA_MIN_SCORE, KNOWLEDGE_QA_NATIONAL_TOP_K, KNOWLEDGE_QA_TOP_K,
)
```

to:

```python
from ingestion.config.settings import (
    KNOWLEDGE_QA_MIN_SCORE, KNOWLEDGE_QA_NATIONAL_TOP_K, KNOWLEDGE_QA_TOP_K,
    KNOWLEDGE_QA_CACHE_ENABLED, KNOWLEDGE_QA_CACHE_THRESHOLD,
    KNOWLEDGE_QA_CACHE_TTL_DAYS,
)
```

- [ ] **Step 2: Add cache params + setup to `__init__`**

Replace the whole `__init__` method:

```python
    def __init__(
        self,
        chunk_repository=None,
        embedder=None,
        gateway=None,
        top_k: int = KNOWLEDGE_QA_TOP_K,
        min_score: float = KNOWLEDGE_QA_MIN_SCORE,
        national_top_k: int = KNOWLEDGE_QA_NATIONAL_TOP_K,
    ):
        self._chunk_repository = chunk_repository or KnowledgeChunkRepository()
        self._embedder = embedder or GeminiEmbedder()
        self._gateway = gateway or build_default_gateway()
        self._top_k = top_k
        self._min_score = min_score
        self._national_top_k = national_top_k
        from services.knowledge.qa_graph import build_kqa_graph
        self._graph = build_kqa_graph(self)
```

with:

```python
    def __init__(
        self,
        chunk_repository=None,
        embedder=None,
        gateway=None,
        top_k: int = KNOWLEDGE_QA_TOP_K,
        min_score: float = KNOWLEDGE_QA_MIN_SCORE,
        national_top_k: int = KNOWLEDGE_QA_NATIONAL_TOP_K,
        cache=None,
        cache_enabled: bool = KNOWLEDGE_QA_CACHE_ENABLED,
        cache_threshold: float = KNOWLEDGE_QA_CACHE_THRESHOLD,
        cache_ttl_days: int = KNOWLEDGE_QA_CACHE_TTL_DAYS,
    ):
        self._chunk_repository = chunk_repository or KnowledgeChunkRepository()
        self._embedder = embedder or GeminiEmbedder()
        self._gateway = gateway or build_default_gateway()
        self._top_k = top_k
        self._min_score = min_score
        self._national_top_k = national_top_k
        # Cache resolution: an explicit repo wins (tests inject a fake); else
        # auto-create when enabled (the production no-arg path); else disabled.
        if cache is not None:
            self._cache = cache
        elif cache_enabled:
            from services.knowledge.qa_cache import QACacheRepository
            self._cache = QACacheRepository()
        else:
            self._cache = None
        self._cache_threshold = cache_threshold
        self._cache_ttl_days = cache_ttl_days
        from services.knowledge.qa_graph import build_kqa_graph
        self._graph = build_kqa_graph(self)
```

- [ ] **Step 3: Extract `_run_graph` (rename the current `answer` body)**

Replace the entire current `answer` method body. The new `answer` is added in Task 2; for now, replace the old `answer` method with the extracted `_run_graph` helper:

```python
    def _run_graph(
        self,
        question: str,
        school: Optional[str],
        topic: Optional[str],
        conversation_context: str,
        query_vector,
        national,
        retrieval_query: Optional[str],
    ) -> KnowledgeQAResult:
        # Facade over the compiled subgraph. The graph nodes call the very same
        # helpers (embed_query, vector_search, _augment_with_national, _generate)
        # with identical embedding precedence and confidence gate. The graph's
        # embed node reuses a supplied query_vector instead of re-embedding.
        from services.knowledge.qa_graph import KQAState
        state = KQAState(
            question=question,
            school=school,
            topic=topic,
            conversation_context=conversation_context,
            query_vector=query_vector,
            national=national,
            retrieval_query=retrieval_query,
        )
        final = self._graph.invoke(state)
        return final["result"] if isinstance(final, dict) else final.result
```

(At this point the class has no `answer` method — Task 2 adds it. Do not run the suite between Task 1 and Task 2; commit them together in Task 2.)

---

### Task 2: `answer()` cache lookup + store

**Files:**
- Modify: `services/knowledge/qa_service.py` (add the new `answer` method directly above `_run_graph`)

**Interfaces:**
- Consumes: `self._cache` (`lookup`/`store`/`scope_keys`/`current_versions`), `self.embed_query`, `self._run_graph`, `self._min_score`, `self._cache_threshold`, `self._cache_ttl_days`.
- Produces: `KnowledgeQAService.answer(question, school, topic, conversation_context="", query_vector=None, national=None, retrieval_query=None) -> KnowledgeQAResult` with the same public signature as before.

- [ ] **Step 1: Add the cache-aware `answer` method**

In `services/knowledge/qa_service.py`, insert this method immediately above `_run_graph`:

```python
    def answer(
        self,
        question: str,
        school: Optional[str],
        topic: Optional[str],
        conversation_context: str = "",
        query_vector=None,
        national=None,
        retrieval_query: Optional[str] = None,
    ) -> KnowledgeQAResult:
        # No cache for cross-school / no-topic calls (the fanout always supplies
        # a concrete (school, topic); direct school=None calls bypass).
        if self._cache is None or school is None or topic is None:
            return self._run_graph(
                question, school, topic, conversation_context,
                query_vector, national, retrieval_query,
            )

        # Embed once: reuse the fanout's vector, else embed the retrieval query.
        embedding = query_vector
        if embedding is None:
            embedding = self.embed_query(retrieval_query or question)

        try:
            hit = self._cache.lookup(embedding, school, topic, self._cache_threshold)
            if hit is not None:
                return hit.to_result(from_cache=True)
        except Exception as exc:  # never let the cache break QA
            logger.warning("knowledge QA cache lookup failed: %r", exc)

        # MISS → normal generation, reusing the embedding (no second embed).
        result = self._run_graph(
            question, school, topic, conversation_context,
            embedding, national, retrieval_query,
        )

        # Quality gate: only cache grounded, confident answers, so a later,
        # better answer (after more docs arrive) is regenerated, not blocked.
        try:
            if result.has_data and result.confidence >= self._min_score:
                dep_versions = self._cache.current_versions(
                    self._cache.scope_keys(school, topic)
                )
                self._cache.store(
                    school, topic, question, embedding, result,
                    dep_versions, self._cache_ttl_days,
                )
        except Exception as exc:
            logger.warning("knowledge QA cache store failed: %r", exc)
        return result
```

- [ ] **Step 2: Run the existing knowledge suite — still green, but noisy**

Run: `python -m pytest tests/services/knowledge/test_qa_service.py tests/services/knowledge/test_qa_graph.py -v`
Expected: PASS. The existing `answer()`-calling tests now construct the service with the cache auto-enabled (default). Their `FakeEmbedder` returns 3-dim vectors, so every cache `lookup`/`store` errors out (dimension mismatch or DB-down) and is swallowed by `answer()`'s try/except — the calls fall through to the graph, so all assertions still hold. The cost is stray DB attempts + `logger.warning` noise, which Task 3 removes cleanly. If any test actually FAILS here, debug with superpowers:systematic-debugging before continuing.

- [ ] **Step 3: Commit Tasks 1 + 2 together**

```bash
git add services/knowledge/qa_service.py
git commit -m "feat(knowledge-qa): wire semantic cache into answer()"
```

---

### Task 3: Opt existing answer()-calling tests out of the cache

**Files:**
- Modify: `tests/services/knowledge/test_qa_service.py` (4 construction sites)
- Modify: `tests/services/knowledge/test_qa_graph.py` (1 construction site)
- Modify: `tests/services/chat/test_knowledge_qa_integration.py` (1 construction site)

**Interfaces:**
- Consumes: `KnowledgeQAService(cache_enabled=False)`.
- Produces: existing tests stay DB-free and behaviour-identical.

Rationale: only `answer()` touches the cache, and only these files call `answer()` with a concrete `(school, topic)`. Disabling the cache (`cache_enabled=False`) keeps them pure unit tests. (`test_qa_retrieve.py`, `test_qa_generate_from_chunks.py`, `test_qa_prompt_source.py` call `retrieve`/`generate_from_chunks`/`_generate`, which never touch the cache — leave them unchanged.)

- [ ] **Step 1: `test_qa_service.py` — `_build` helper**

In `tests/services/knowledge/test_qa_service.py`, in `_build`, add `cache_enabled=False,` to the constructor:

```python
    service = KnowledgeQAService(
        chunk_repository=repo,
        embedder=embedder,
        gateway=gateway,
        min_score=min_score,
        top_k=top_k,
        cache_enabled=False,
    )
```

- [ ] **Step 2: `test_qa_service.py` — `_service_with` helper**

```python
def _service_with(repo, parsed_data, min_score=0.5, top_k=5):
    return KnowledgeQAService(
        chunk_repository=repo,
        embedder=FakeEmbedder(),
        gateway=FakeGateway(parsed_data=parsed_data),
        min_score=min_score,
        top_k=top_k,
        cache_enabled=False,
    )
```

- [ ] **Step 3: `test_qa_service.py` — two inline constructions**

In `test_answer_uses_supplied_query_vector_without_embedding`, change:

```python
    service = KnowledgeQAService(chunk_repository=repo, embedder=embedder, gateway=object())
```
to:
```python
    service = KnowledgeQAService(chunk_repository=repo, embedder=embedder, gateway=object(), cache_enabled=False)
```

In `test_answer_uses_supplied_national_without_research`, change:

```python
    service = KnowledgeQAService(chunk_repository=repo, embedder=object(), gateway=object())
```
to:
```python
    service = KnowledgeQAService(chunk_repository=repo, embedder=object(), gateway=object(), cache_enabled=False)
```

- [ ] **Step 4: `test_qa_graph.py` — `_service` helper**

```python
def _service(chunks, min_score=0.2, answer="Học phí 15 triệu/năm."):
    return KnowledgeQAService(
        chunk_repository=_FakeRepo(chunks),
        embedder=_FakeEmbedder(),
        gateway=_FakeGateway(answer),
        min_score=min_score,
        cache_enabled=False,
    )
```

- [ ] **Step 5: `test_knowledge_qa_integration.py` — `_service` helper**

In `tests/services/chat/test_knowledge_qa_integration.py`, in `_service`, add `cache_enabled=False,`:

```python
    qa = KnowledgeQAService(
        chunk_repository=corpus,
        embedder=_Embedder(),
        gateway=_Gateway(parsed),
        min_score=0.5,
        cache_enabled=False,
    )
```

- [ ] **Step 6: Run the affected suites to verify green**

Run: `python -m pytest tests/services/knowledge/test_qa_service.py tests/services/knowledge/test_qa_graph.py tests/services/chat/test_knowledge_qa_integration.py -q`
Expected: PASS, no DB warnings.

- [ ] **Step 7: Commit**

```bash
git add tests/services/knowledge/test_qa_service.py tests/services/knowledge/test_qa_graph.py tests/services/chat/test_knowledge_qa_integration.py
git commit -m "test(knowledge-qa): disable cache in existing answer() unit tests"
```

---

### Task 4: Cache-behaviour unit tests (fake cache)

**Files:**
- Test: `tests/services/knowledge/test_qa_service_cache.py`

**Interfaces:**
- Consumes: `KnowledgeQAService(cache=<fake>)`, `CachedAnswer`, `ScoredChunk`, `InferenceResult`.
- Produces: the spec's unit coverage (hit / below-threshold miss / quality gate / school|topic None bypass / lookup degrade).

- [ ] **Step 1: Write the failing behaviour tests**

Create `tests/services/knowledge/test_qa_service_cache.py`:

```python
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

    def vector_search(self, embedding, school=None, topic=None, limit=5):
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
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/services/knowledge/test_qa_service_cache.py -v`
Expected: PASS (all eight cases).

- [ ] **Step 3: Run the whole knowledge suite for regressions**

Run: `python -m pytest tests/services/knowledge tests/services/chat/test_knowledge_qa_integration.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/services/knowledge/test_qa_service_cache.py
git commit -m "test(knowledge-qa): cover answer() cache hit/miss/gate/bypass"
```

---

## Self-Review (run after completing all tasks)

- **Spec coverage (§answer wiring + §quality gate + §testing/unit):** disabled / `school is None` / `topic is None` → bypass (✓ Task 4 + answer guard); embed-once reuse via `query_vector` into the graph (✓ Task 2 + `test_supplied_query_vector_*`); hit returns `from_cache=True`, no generation (✓); below-threshold miss → generation, then store only if `has_data and confidence >= min_score` (✓ `test_below_threshold` / `test_no_data` / `test_cache_miss_generates_then_stores`); lookup/store wrapped + `logger.warning` (✓ Task 2 + `test_lookup_failure_degrades`).
- **No placeholders:** every step has exact code and an exact command.
- **Type consistency:** `answer()` keeps its original public signature; `_run_graph` takes the same args the old body used; `hit.to_result(from_cache=True)` and `store(school, topic, question, embedding, result, dep_versions, ttl_days)` match Plan 02's `CachedAnswer`/`store` exactly; `dep_versions` is built from `current_versions(scope_keys(...))` (Plan 01).
