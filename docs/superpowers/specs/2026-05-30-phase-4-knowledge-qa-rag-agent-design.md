# Phase 4 — KnowledgeQA RAG Agent — Design Spec

**Date:** 2026-05-30
**Status:** Approved
**Parent spec:** [`2026-05-30-intent-router-and-knowledge-qa-design.md`](./2026-05-30-intent-router-and-knowledge-qa-design.md) (Phase 4 section)

## Problem

The intent router (Phase 1) already routes off-topic questions ("học phí trường này bao nhiêu?", "chương trình học gồm gì?") to `KNOWLEDGE_QA`, but `ConversationService._handle_knowledge_qa()` is still a stub that always returns the "chưa có dữ liệu" fallback. Phases 2–3 built the corpus (`knowledge_chunks` with pgvector HNSW, cosine) and the ingestion pipeline. Phase 4 fills the seam: a RAG service that answers from the corpus, **cites its sources**, and **never invents** an answer when retrieval is weak.

## What already exists (Phase 4 builds on this)

| Capability | Location | Signature / detail |
|---|---|---|
| Vector search | `services/knowledge/repository.py` | `vector_search(embedding, school=None, topic=None, limit=5) -> List[ScoredChunk]`; cosine via `<=>`, `score = 1 - distance` (~[0,1]); metadata filter applied **before** the vector search |
| Chunk / scored models | `services/knowledge/models.py` | `KnowledgeChunk`, `ScoredChunk(score: float)` |
| Embedding | `ingestion/knowledge/embedder.py` | `GeminiEmbedder.embed(texts) -> list[list[float]]`, **sync**, L2-normalized, 768-dim, currently hardcodes `task_type="RETRIEVAL_DOCUMENT"` |
| LLM gateway | `services/inference/gateway.py` | `LLMGateway.run(InferenceRequest) -> InferenceResult`; JSON mode → `parsed_data` |
| Intent routing | `services/chat/intent_router.py` | `classify(message, profile_state) -> IntentResult{route, topic, school}`; resolves pronouns from `preferred_schools` |
| Chat seam | `services/chat/conversation_service.py` | `_handle_knowledge_qa(...)` — **stub** to be implemented |
| DB | `db/migrations/013_knowledge_corpus.sql` | `knowledge_chunks` HNSW `vector_cosine_ops`, `UNIQUE(source_url, span_start, span_end)` |

No `KnowledgeQAService` exists yet. No reranker exists.

## Resolved design decisions

1. **No separate reranker.** `vector_search`'s metadata pre-filter (school + topic) already enforces exactness before the cosine search, so a heuristic re-score is largely redundant and an LLM rerank spends latency/cost against the 5s p95 budget for marginal gain on a small corpus. Take pgvector's top-K and apply the threshold. Reranking is an isolated add-on later if precision proves bad.

2. **Citations via LLM-marked usage with deterministic fallback.** The generation call returns JSON `{answer, used_source_ids}`; citations = the chunks the model says it used (deduped by `source_url`). When an answer is present but `used_source_ids` is empty/invalid, citations fall back to "all above-threshold chunks that were passed". When the generation produces *no usable answer text at all* (JSON structure failure / empty `answer`), the service degrades to the no-data fallback rather than fabricating. This serves the core *no bịa* (no hallucination) value, reuses the system's reliable JSON-output infra (intent router, profile service), and stays robust.

3. **Threshold gate before the LLM.** If retrieval is empty or top score `< min_score`, return "no data" **without calling the LLM** — guarantees zero hallucination on weak retrieval and saves a round-trip.

4. **Reuse the existing no-data fallback text** (the current `_TOPIC_LABELS` message) rather than introducing a second wording.

5. **`gemini-2.5-flash` for generation** (stronger grounding than the flash-lite default), JSON output, temperature 0.0.

## Architecture

### Pipeline

```
question + { school, topic } (+ conversation_context)
  ↓ embed query (RETRIEVAL_QUERY)
  ↓ vector_search(emb, school, topic, limit=top_k)   # metadata pre-filter + cosine
  ↓ confidence = top chunk score
  ↓ IF no chunks OR confidence < min_score → has_data=False  (NO LLM call)
  ↓ ELSE generate (JSON: {answer, used_source_ids}) grounded in numbered chunks
  ↓ citations = used chunks (dedup by source_url); fallback = all passed chunks
  → KnowledgeQAResult
```

### Service

`services/knowledge/qa_service.py` → **`KnowledgeQAService`**. Owns the RAG pipeline only; the chat layer renders the result. Dependencies injected, with lazy production defaults so production construction is param-free and tests inject fakes.

```python
KnowledgeQAService(
    chunk_repository: KnowledgeChunkRepository,
    embedder: GeminiEmbedder,
    gateway: LLMGateway,
    top_k: int = KNOWLEDGE_QA_TOP_K,          # 5
    min_score: float = KNOWLEDGE_QA_MIN_SCORE, # 0.5
)
```

### Interface & result model

```python
# services/knowledge/models.py (alongside KnowledgeChunk)
class Citation(BaseModel):
    source_url: str
    chunk_text: str

class KnowledgeQAResult(BaseModel):
    has_data: bool
    answer: Optional[str] = None      # None when has_data is False
    citations: list[Citation] = []
    confidence: float = 0.0           # top chunk cosine score

# KnowledgeQAService
def answer(self, question: str, school: Optional[str], topic: Optional[str],
           conversation_context: str = "") -> KnowledgeQAResult: ...
```

### `answer()` steps

1. **Embed query** — `embedder.embed([question], task_type="RETRIEVAL_QUERY")[0]`.
2. **Retrieve** — `chunk_repository.vector_search(emb, school=school, topic=topic, limit=top_k)`.
3. **Confidence** — `chunks[0].score if chunks else 0.0`.
4. **Threshold gate** — no chunks or `confidence < min_score` → `KnowledgeQAResult(has_data=False, confidence=...)`, no LLM call.
5. **Generate** — prompt with chunks numbered `[1]…[k]`; gateway JSON → `{answer, used_source_ids}`.
6. **Citations** — chunks whose number ∈ `used_source_ids`, deduped by `source_url`; parse-fail/empty → all passed chunks. Return `has_data=True`.

Data path = 2 network round-trips (embed + generate); no-data path = 1 (embed only). Within the 5s p95 budget.

### Grounding prompt (hard rule)

Vietnamese system prompt instructs the model to: answer **only** from the numbered passages; never add outside information; if the passages don't cover the question, say so rather than guess; output strict JSON `{"answer": str, "used_source_ids": [int]}`. `conversation_context` is included only to keep phrasing / pronoun continuity natural — retrieval is already keyed on the router's `school` / `topic`.

> Chỉ trả lời dựa trên các đoạn văn bản được cung cấp. Nếu không đủ bằng chứng, nói rõ là chưa có dữ liệu. Không suy diễn hoặc bổ sung thông tin ngoài context.

## Chat wiring — `_handle_knowledge_qa`

- Inject `knowledge_qa` into `ConversationService.__init__` (same pattern as `intent_router`).
- **School resolution:** `school = intent.school or (profile_state.preferred_schools[0] if any else None)`. `topic = intent.topic` (None → broader search).
- Call `knowledge_qa.answer(question=content, school=..., topic=..., conversation_context="")`:
  - **`has_data`** → assistant message = `answer` + appended deduped `Nguồn:` URL list; apply `_append_return_prompt` (mid-flow re-ask preserved); return `ConversationTurnResult` carrying `citations`, `should_start_run=False`. **Profile / flow state untouched.**
  - **no data** → reuse the existing `_TOPIC_LABELS` fallback text (unchanged) + `_append_return_prompt`.
  - **`answer()` raises** (embed / LLM / DB error) → caught → same graceful fallback text. The chat never breaks.
- `ConversationTurnResult` gains `citations: list[Citation] = []` (empty for every other branch — backward compatible). `Citation` imported from `services/knowledge/models.py`.

## Supporting edits

- `ingestion/knowledge/embedder.py` — `embed(texts, task_type="RETRIEVAL_DOCUMENT")`; QA passes `RETRIEVAL_QUERY`. Ingestion default unchanged.
- `ingestion/config/settings.py` — `KNOWLEDGE_QA_TOP_K = 5`, `KNOWLEDGE_QA_MIN_SCORE = 0.5` (env-overridable, next to `EMBEDDING_DIM`).
- `services/inference/factory.py` + registry — register `knowledge_qa_agent` → `gemini-2.5-flash`, JSON output, temp 0.0, retry with flash-lite fallback.

## Error handling

| Situation | Behavior |
|---|---|
| Retrieval empty or `confidence < min_score` | `has_data=False`, no LLM call, reuse existing fallback text |
| Generation produces no usable answer text (JSON structure failure / empty `answer`) | `has_data=False` → reuse the no-data fallback; never fabricate |
| Answer text present but `used_source_ids` empty/invalid | `has_data=True`; citations = all passed above-threshold chunks |
| `embedder` / `gateway` / repository raises inside `answer()` | service catches the gateway error and degrades to `has_data=False`; `ConversationService` also wraps the call so a raised embed/DB error → graceful "chưa có dữ liệu" fallback; chat never breaks |
| `intent.school` null and no `preferred_schools` | `school=None` → topic-only search; threshold gate still guards quality |

## Testing strategy

**`tests/services/knowledge/test_qa_service.py`** (FakeEmbedder / FakeChunkRepo / FakeGateway):
- Data present, `confidence ≥ threshold` → grounded answer + citations resolved from `used_source_ids`.
- `confidence < threshold` → `has_data=False` **and gateway never called** (assert no call).
- No chunks → `has_data=False`.
- JSON parse-fail → citations fall back to all passed chunks, `has_data=True`.
- Empty `used_source_ids` → fallback citations.
- Query embedded with `task_type="RETRIEVAL_QUERY"` (assert).

**`tests/services/chat/test_conversation_service.py`** (extend with `FakeKnowledgeQA`):
- `KNOWLEDGE_QA` + has_data → answer surfaced, `citations` on result, `Nguồn:` appended, profile/flow **not reset**.
- `KNOWLEDGE_QA` + no data → existing fallback text, `_append_return_prompt` fires mid-flow.
- `intent.school` null → resolved from `preferred_schools`.
- `knowledge_qa.answer` raises → graceful fallback, chat does not break.

**Integration (acceptance)**: in-memory mock corpus → query → assert answer grounded in corpus; `citations` carry `source_url` + `chunk_text`.

**Embedder**: `embed(texts, task_type=...)` passes `task_type` through to the client config.

## Acceptance Criteria (from parent spec)

- [ ] `"Học phí VNU-UET bao nhiêu?"` → answer with figures + `source_url` (when data ingested)
- [ ] Topic with no data → clear fallback message, **no invented figures**
- [ ] `citations` contain matching `source_url` and `chunk_text`
- [ ] Confidence `< threshold` (default 0.5) → automatic fallback, no generation
- [ ] `school` resolved from conversation context when user says "trường này" (router + `preferred_schools` fallback)
- [ ] Integration test: mock corpus → query → assert answer grounded in corpus
- [ ] KnowledgeQA pipeline response time `< 5s` (p95) in test environment

## Out of scope (named, to keep focus)

- Reranker (add-on only if precision proves bad once real data lands)
- HYBRID orchestration / `CompareAgent` (Phase 5)
- QA-path tracing/telemetry parity with the advisory graph
- Corpus data ingestion (Phase 3)

## Not changed

- Advisory graph (`profile → retrieve → conflict → reason → policy → explain`)
- Structured admission schema and ingestion pipeline
- Intent router behavior and `FlowState` semantics (Phase 1)
- Ingestion embedding behavior (default `task_type` stays `RETRIEVAL_DOCUMENT`)
