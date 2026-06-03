import logging
from typing import Optional

from ingestion.config.settings import KNOWLEDGE_QA_MIN_SCORE, KNOWLEDGE_QA_TOP_K
from ingestion.knowledge.embedder import GeminiEmbedder
from services import build_default_gateway
from services.inference.models import InferenceRequest
from services.knowledge.models import Citation, KnowledgeQAResult
from services.knowledge.repository import KnowledgeChunkRepository

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
    ):
        self._chunk_repository = chunk_repository or KnowledgeChunkRepository()
        self._embedder = embedder or GeminiEmbedder()
        self._gateway = gateway or build_default_gateway()
        self._top_k = top_k
        self._min_score = min_score

    def answer(
        self,
        question: str,
        school: Optional[str],
        topic: Optional[str],
        conversation_context: str = "",
    ) -> KnowledgeQAResult:
        embedding = self._embedder.embed([question], task_type="RETRIEVAL_QUERY")[0]
        chunks = self._chunk_repository.vector_search(
            embedding, school=school, topic=topic, limit=self._top_k
        )
        confidence = chunks[0].score if chunks else 0.0
        if not chunks or confidence < self._min_score:
            return KnowledgeQAResult(has_data=False, confidence=confidence)
        return self._generate(question, chunks, confidence, conversation_context)

    def _generate(self, question, chunks, confidence, conversation_context) -> KnowledgeQAResult:
        try:
            result = self._gateway.run(
                InferenceRequest(
                    agent_name="knowledge_qa_agent",
                    task_type="knowledge_qa",
                    system_prompt=KNOWLEDGE_QA_SYSTEM_PROMPT,
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
            selected = list(chunks)  # deterministic fallback: cite every passed chunk

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
