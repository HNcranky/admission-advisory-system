import logging

from services.chat.hybrid_models import KnowledgeBlock

logger = logging.getLogger(__name__)


def _resolve_schools(intent, school_fallback):
    if intent.schools:
        return list(intent.schools)
    if intent.school:
        return [intent.school]
    if school_fallback:
        return [school_fallback]
    return [None]


def _resolve_topics(intent):
    if intent.topics:
        return list(intent.topics)
    if intent.topic:
        return [intent.topic]
    return [None]


def run_knowledge_fanout(knowledge_qa, intent, content, school_fallback=None) -> list:
    """Call the single-school KnowledgeQA once per (school, topic) pair.

    Each call swallows its own error → a no-data KnowledgeBlock; siblings survive.
    """
    blocks = []
    for school in _resolve_schools(intent, school_fallback):
        for topic in _resolve_topics(intent):
            try:
                result = knowledge_qa.answer(
                    question=content, school=school, topic=topic, conversation_context="",
                )
            except Exception as exc:
                logger.warning(
                    "knowledge fan-out failed for school=%r topic=%r: %r", school, topic, exc
                )
                result = None
            if result is not None and result.has_data and result.answer:
                sources = [c.source_url for c in result.citations if c.source_url]
                blocks.append(KnowledgeBlock(
                    school=school, topic=topic, has_data=True,
                    answer=result.answer, sources=sources,
                ))
            else:
                blocks.append(KnowledgeBlock(school=school, topic=topic, has_data=False))
    return blocks


def format_knowledge_blocks(blocks) -> str:
    """Deterministic rendering of knowledge blocks for the inline (no-synthesis) path."""
    lines = []
    for block in blocks:
        if block.has_data and block.answer:
            label = block.school or ""
            body = f"{label}: {block.answer}" if label else block.answer
            if block.sources:
                body += "\n" + "\n".join(f"- {url}" for url in block.sources)
            lines.append(body)
    if not lines:
        return (
            "Hệ thống chưa có dữ liệu cho thông tin bạn hỏi. "
            "Bạn có thể liên hệ trực tiếp nhà trường để biết thêm chi tiết."
        )
    return "\n\n".join(lines)
