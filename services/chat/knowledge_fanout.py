import logging
from concurrent.futures import ThreadPoolExecutor

from services.chat.hybrid_models import KnowledgeBlock
from services.knowledge.retrieval_query import build_retrieval_query

logger = logging.getLogger(__name__)

_FANOUT_MAX_WORKERS = 4


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


def run_knowledge_fanout(knowledge_qa, intent, content, school_fallback=None, conversation_context="", prev_user="") -> list:
    """Call the single-school KnowledgeQA once per (school, topic) pair, in parallel.

    Each call swallows its own error → a no-data KnowledgeBlock; siblings survive.
    Block order matches the original (school, topic) iteration order.
    The query is embedded once and shared across all calls (see spec §1c).
    """
    tasks = [
        (school, topic)
        for school in _resolve_schools(intent, school_fallback)
        for topic in _resolve_topics(intent)
    ]

    # Embed the (optionally context-augmented) query once for the whole fan-out.
    # An elided follow-up gets its referent from prev_user; standalone questions
    # are embedded verbatim. On failure, leave the vector None so each answer()
    # embeds the original question internally (resilience over the micro-opt).
    retrieval_text = build_retrieval_query(content, prev_user)
    query_vector = None
    try:
        query_vector = knowledge_qa.embed_query(retrieval_text)
    except Exception as exc:
        logger.warning("knowledge fan-out query embed failed, per-call fallback: %r", exc)

    # Precompute national-scope chunks once per distinct topic (the national search
    # depends only on the topic, not the school). Skipped when the embed failed
    # (query_vector is None) → each answer() self-serves national, unchanged path.
    national_by_topic = {}
    if query_vector is not None:
        for topic in {t for _, t in tasks}:
            try:
                national_by_topic[topic] = knowledge_qa.national_chunks(query_vector, topic)
            except Exception as exc:
                logger.warning("national precompute failed for topic=%r: %r", topic, exc)

    def _answer_one(task):
        school, topic = task
        try:
            return knowledge_qa.answer(
                question=content, school=school, topic=topic,
                conversation_context=conversation_context,
                query_vector=query_vector,
                national=national_by_topic.get(topic),
            )
        except Exception as exc:
            logger.warning(
                "knowledge fan-out failed for school=%r topic=%r: %r", school, topic, exc
            )
            return None

    if len(tasks) <= 1:
        results = [_answer_one(task) for task in tasks]
    else:
        with ThreadPoolExecutor(max_workers=min(_FANOUT_MAX_WORKERS, len(tasks))) as executor:
            results = list(executor.map(_answer_one, tasks))

    blocks = []
    for (school, topic), result in zip(tasks, results):
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
