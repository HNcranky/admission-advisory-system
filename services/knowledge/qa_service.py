import logging
from typing import Optional

from ingestion.config.settings import (
    KNOWLEDGE_QA_MIN_SCORE, KNOWLEDGE_QA_NATIONAL_TOP_K, KNOWLEDGE_QA_TOP_K,
    KNOWLEDGE_QA_CACHE_ENABLED, KNOWLEDGE_QA_CACHE_THRESHOLD,
    KNOWLEDGE_QA_CACHE_TTL_DAYS,
)
from observability.prompts import get_prompt_service
from services.inference.embedder import GeminiEmbedder
from services import build_default_gateway
from services.inference.models import InferenceRequest
from services.knowledge.models import Citation, KnowledgeQAResult
from services.knowledge.repository import KnowledgeChunkRepository
from services.knowledge.scope import NATIONAL_SCHOOL

logger = logging.getLogger(__name__)

KNOWLEDGE_QA_SYSTEM_PROMPT = """
Bạn là trợ lý trả lời câu hỏi về thông tin tuyển sinh đại học Việt Nam,
chỉ dựa trên các đoạn văn bản được cung cấp.

Quy tắc bắt buộc:
- Chỉ trả lời dựa trên các đoạn văn bản tham khảo được đánh số bên dưới.
- Tuyệt đối không suy diễn hay bổ sung thông tin ngoài các đoạn đó.
- Nếu các đoạn không đủ thông tin để trả lời, để "answer" là chuỗi rỗng "".
- Trả lời ngắn gọn, đúng trọng tâm, bằng tiếng Việt.

Trả về JSON hợp lệ, không giải thích thêm:
{"answer": "<câu trả lời hoặc chuỗi rỗng>", "used_source_ids": [<số thứ tự các đoạn đã dùng>]}
""".strip()


class KnowledgeQAService:
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

    def embed_query(self, question: str):
        """Embed a retrieval query. Exposed so callers (e.g. the fan-out) can
        embed once and reuse the vector across many answer() calls."""
        return self._embedder.embed([question], task_type="RETRIEVAL_QUERY")[0]

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

    def retrieve(self, question: str, school, topic):
        """Production-equivalent retrieval (embed → vector_search → national
        augment), exposed so the eval curation can freeze the same chunks
        production would surface. Mirrors answer()'s retrieval branch."""
        embedding = self.embed_query(question)
        chunks = self._chunk_repository.vector_search(
            embedding, school=school, topic=topic, limit=self._top_k
        )
        return self._augment_with_national(embedding, school, topic, chunks)

    def generate_from_chunks(
        self, question: str, chunks, conversation_context: str = ""
    ) -> KnowledgeQAResult:
        """Eval hook: run only the model-dependent generation step on a fixed set
        of chunks, bypassing retrieval. Mirrors the post-retrieval branch of
        answer(), so what it measures is exactly what production runs."""
        confidence = chunks[0].score if chunks else 0.0
        if not chunks:
            return KnowledgeQAResult(has_data=False, confidence=confidence)
        return self._generate(question, chunks, confidence, conversation_context)

    def national_chunks(self, query_vector, topic):
        """National-scope (Bộ GD&ĐT) chunks for a topic, score-filtered. The result
        depends only on the topic, not the school, so the fan-out can compute this
        once per distinct topic and reuse it across schools."""
        national = self._chunk_repository.vector_search(
            query_vector, school=NATIONAL_SCHOOL, topic=topic,
            limit=self._national_top_k,
        )
        return [c for c in national if c.score >= self._min_score]

    def _augment_with_national(self, embedding, school, topic, chunks, national=None):
        """A school-scoped query also pulls national-scope (Bộ GD&ĐT) chunks with
        their own budget — national regulations apply to every school. The two
        scopes keep separate top_k, so national never crowds out the school's own
        chunks. Skipped when the query isn't school-scoped (school=None already
        scans national chunks) or is already national.

        A precomputed ``national`` list (e.g. from the fan-out) is reused as-is;
        otherwise national chunks are fetched on demand."""
        if school in (None, NATIONAL_SCHOOL):
            return chunks
        if national is None:
            national = self.national_chunks(embedding, topic)
        merged = list(chunks) + list(national)
        merged.sort(key=lambda c: c.score, reverse=True)
        return merged

    def _generate(self, question, chunks, confidence, conversation_context) -> KnowledgeQAResult:
        try:
            cp = get_prompt_service().get("knowledge-qa", fallback=KNOWLEDGE_QA_SYSTEM_PROMPT)
            result = self._gateway.run(
                InferenceRequest(
                    agent_name="knowledge_qa_agent",
                    task_type="knowledge_qa",
                    system_prompt=cp.text,
                    prompt=cp.handle,
                    user_prompt=self._build_user_prompt(question, chunks, conversation_context),
                    output_mode="json",
                    temperature=0.0,
                )
            )
            data = result.parsed_data or {}
        except Exception as exc:
            # Degrade to no-data rather than crash, but surface the failure so a
            # silent LLM/embedding outage doesn't look like "no knowledge".
            logger.warning("knowledge QA generation failed: %r", exc)
            data = {}

        answer_text = str(data.get("answer") or "").strip()
        if not answer_text:
            # No grounded answer produced → degrade rather than fabricate.
            return KnowledgeQAResult(has_data=False, confidence=confidence)

        citations = self._resolve_citations(chunks, data.get("used_source_ids"))
        return KnowledgeQAResult(
            has_data=True,
            answer=answer_text,
            citations=citations,
            confidence=confidence,
        )

    @staticmethod
    def _resolve_citations(chunks, used_source_ids) -> list:
        ids = used_source_ids if isinstance(used_source_ids, list) else []
        selected = [
            chunks[i - 1]
            for i in ids
            if isinstance(i, int) and 1 <= i <= len(chunks)
        ]
        if not selected:
            selected = chunks[:1]  # fallback: cite only the top-scored chunk

        citations = []
        seen = set()
        for chunk in selected:
            url = chunk.source_url or ""
            key = url if url else ("", chunk.chunk_text)  # don't collapse distinct unsourced chunks
            if key in seen:
                continue
            seen.add(key)
            citations.append(Citation(source_url=url, chunk_text=chunk.chunk_text))
        return citations

    @staticmethod
    def _build_user_prompt(question, chunks, conversation_context) -> str:
        lines = []
        if conversation_context:
            lines.append(f"Ngữ cảnh hội thoại trước đó:\n{conversation_context}\n")
        lines.append("Các đoạn văn bản tham khảo (đánh số):")
        for i, chunk in enumerate(chunks, start=1):
            lines.append(f"[{i}] {chunk.chunk_text}")
        lines.append(f"\nCâu hỏi: {question}")
        return "\n".join(lines)
