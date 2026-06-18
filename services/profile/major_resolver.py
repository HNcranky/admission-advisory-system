import logging
from typing import List, Optional

from services.inference.models import InferenceError
from services.profile_service import extract_preferred_majors, normalize_text

logger = logging.getLogger(__name__)


def _dedupe(items: List[str]) -> List[str]:
    return list(dict.fromkeys(items))


# Cue phân loại ngành đã chọn (explicit) vs sở thích suy luận (inferred) — AC4.
_EXPLICIT_CUES = (
    "uu tien", "chon ", "quyet dinh", "muon hoc nganh", "dang ky nganh",
    "chac chan", "xet tuyen nganh",
)
_VAGUE_CUES = ("thich", "dam me", "quan tam", "huong toi", "voi ai", "lien quan", "so thich")


# Cue thể hiện Ý ĐỊNH NGÀNH (sở thích/định hướng/lựa chọn). CHỈ khi có cue mới chạy
# Tier-2/3 (embedding/LLM). Câu hỏi thông tin ("học phí", "điểm chuẩn", "tìm hiểu"...)
# không có cue → skip, tránh embedding kéo ngành tiếp tuyến làm nhiễu preferred_majors.
_MAJOR_INTENT_CUES = (
    "thich", "dam me", "yeu thich", "so thich", "quan tam", "hung thu",
    "huong toi", "dinh huong", "theo duoi", "uoc mo", "mo uoc",
    "muon hoc", "muon theo", "muon lam", "hoc nganh", "chon nganh",
    "dang ky nganh", "xet tuyen nganh", "nen hoc nganh", "nganh nao",
)


def _has_major_intent(text: str) -> bool:
    """True nếu text thể hiện ý định/sở thích NGÀNH (đủ để chạy embedding/LLM)."""
    normalized = normalize_text(text or "")
    return any(cue in normalized for cue in _MAJOR_INTENT_CUES)


def is_explicit_choice(message: str, active_slot: Optional[str] = None) -> bool:
    """True nếu message là LỰA CHỌN ngành rõ ràng (explicit), False nếu chỉ là sở
    thích suy luận (inferred). Trả lời đúng câu hỏi ngành (active_slot) cũng tính
    là explicit; cue mơ hồ ('thích', 'với AI'...) ép về inferred."""
    if active_slot == "preferred_majors":
        return True
    normalized = normalize_text(message or "")
    if any(cue in normalized for cue in _VAGUE_CUES):
        return False
    return any(cue in normalized for cue in _EXPLICIT_CUES)


def resolve_majors(text: str, *, known_state=None, cheap_only: bool = False, top_k: int = 8,
                   score_threshold: float = 0.55, high_threshold: float = 0.70,
                   margin: float = 0.08, gateway=None, embedder=None,
                   repository=None, active_slot: Optional[str] = None) -> List[str]:
    """Free-text -> list[program_id]. Tiered, deterministic-first.

    cheap_only=True: chỉ chạy Tier-1 (alias) rẻ, KHÔNG gọi embedding/LLM — dùng khi
    message rõ ràng đang trả lời một slot khác (chống nhiễu inferred tags).

    Cổng intent: Tier-2/3 (embedding/LLM) chỉ chạy khi text có ý định ngành
    (_has_major_intent) HOẶC đang trả lời slot ngành (active_slot=="preferred_majors").
    Câu hỏi thông tin ("học phí UET") không có ý định ngành → trả [] sau Tier-1."""
    text = text or ""

    # Tier 1 — alias/exact match (rẻ, không LLM/embedding).
    hits = extract_preferred_majors(normalize_text(text))
    if hits:
        return _dedupe(hits)

    if cheap_only:
        return []

    # Cổng intent — không có ý định ngành thì DỪNG trước embedding (trừ khi đang
    # trả lời đúng slot ngành). Chống "học phí UET" → ép ra ngành tiếp tuyến.
    if active_slot != "preferred_majors" and not _has_major_intent(text):
        return []

    # Tier 2 — embedding retrieval top-K từ DB (scale theo catalog, prompt cố định).
    from services.profile.major_catalog_repository import ProgramCatalogRepository
    repository = repository or ProgramCatalogRepository()
    if embedder is None:
        from services.inference.embedder import GeminiEmbedder
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
