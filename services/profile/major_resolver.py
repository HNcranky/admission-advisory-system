import logging
from typing import List, Optional

from services.inference.models import InferenceError
from services.profile_service import extract_preferred_majors, normalize_text

logger = logging.getLogger(__name__)


def _dedupe(items: List[str]) -> List[str]:
    return list(dict.fromkeys(items))


def resolve_majors(text: str, *, known_state=None, top_k: int = 8,
                   score_threshold: float = 0.55, high_threshold: float = 0.70,
                   margin: float = 0.08, gateway=None, embedder=None,
                   repository=None) -> List[str]:
    """Free-text -> list[program_id]. Tiered, deterministic-first."""
    text = text or ""

    # Tier 1 — alias/exact match (rẻ, không LLM/embedding).
    hits = extract_preferred_majors(normalize_text(text))
    if hits:
        return _dedupe(hits)

    # Tier 2 — embedding retrieval top-K từ DB (scale theo catalog, prompt cố định).
    from services.profile.major_catalog_repository import ProgramCatalogRepository
    repository = repository or ProgramCatalogRepository()
    if embedder is None:
        from ingestion.knowledge.embedder import GeminiEmbedder
        embedder = GeminiEmbedder()

    try:
        query_vec = embedder.embed([text], task_type="RETRIEVAL_QUERY")[0]
        candidates = repository.vector_search_programs(query_vec, limit=top_k)
    except Exception as exc:  # embedding/DB lỗi → degrade
        logger.warning("major resolver Tier2 embedding/search failed: %r", exc)
        return []

    strong = [c for c in candidates if c.score >= score_threshold]
    if not strong:
        return []

    confident = len(strong) == 1 or (strong[0].score - strong[1].score) > margin
    if confident:
        top = [c.program_id for c in strong if c.score >= high_threshold]
        return top or [strong[0].program_id]

    # Tier 3 — LLM chọn TẬP CON liên quan trong shortlist (prompt = K ứng viên, cố định).
    if gateway is None:
        from services import build_default_gateway
        gateway = build_default_gateway()
    try:
        picked = _llm_pick_from_shortlist(text, strong, gateway)
        allowed = {c.program_id for c in strong}
        picked = [p for p in picked if p in allowed]
        return picked or [strong[0].program_id]
    except InferenceError as exc:
        logger.warning("major resolver Tier3 LLM failed, dùng top embedding: %r", exc)
        return [strong[0].program_id]


_PICK_PROMPT = (
    "Người dùng mô tả sở thích/định hướng học tập. Cho danh sách ngành ứng viên "
    "(id: tên). Chọn các id NGÀNH PHÙ HỢP NHẤT (có thể nhiều, có thể một). "
    'Trả JSON {"program_ids": [...]} chỉ gồm id trong danh sách, không giải thích.'
)


def _llm_pick_from_shortlist(text: str, strong, gateway) -> List[str]:
    from services.inference.models import InferenceRequest
    shortlist = "\n".join(f"- {c.program_id}: {c.canonical_name}" for c in strong)
    result = gateway.run(InferenceRequest(
        agent_name="major_resolver",
        task_type="major_disambiguation",
        system_prompt=_PICK_PROMPT,
        user_prompt=f'Mô tả: "{text}"\n\nỨng viên:\n{shortlist}',
        output_mode="json",
        temperature=0.0,
    ))
    data = result.parsed_data or {}
    ids = data.get("program_ids") or []
    return [str(i) for i in ids if isinstance(i, (str,))]
