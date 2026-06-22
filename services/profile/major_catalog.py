import logging
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from services.inference.embedder import GeminiEmbedder
from services.knowledge.repository import chunk_content_hash
from services.profile.major_catalog_repository import ProgramCatalogRepository
from services.profile_service import load_program_aliases

logger = logging.getLogger(__name__)


@dataclass
class CatalogBuildReport:
    total: int
    embedded: int
    reused: int


def _embed_input(canonical_name: str, aliases_text: str) -> str:
    base = (canonical_name or "").strip()
    aliases_text = (aliases_text or "").strip()
    return f"{base}. Tên gọi khác: {aliases_text}" if aliases_text else base


def _enrich(program_id: str) -> Tuple[str, Optional[str]]:
    """aliases_text + field từ programs.json nếu khớp program_id; else ("", None)."""
    alias_map = load_program_aliases()
    payload = alias_map.get(program_id)
    if not payload:
        return ("", None)
    aliases = [a for a in payload.get("aliases", []) if a]
    return (", ".join(aliases), None)


def _load_canonical_programs() -> List[Tuple[Optional[str], str]]:
    from ingestion.storage.db_connection import get_cursor
    with get_cursor(commit=False) as cur:
        cur.execute(
            "SELECT DISTINCT program_id, program_name_canonical "
            "FROM canonical_admission_records"
        )
        return [(row[0], row[1] or "") for row in cur.fetchall()]


def build_major_catalog(*, source_programs: Optional[Callable] = None,
                        repository: Optional[ProgramCatalogRepository] = None,
                        embedder=None, enrich: Optional[Callable] = None) -> CatalogBuildReport:
    source_programs = source_programs or _load_canonical_programs
    repository = repository or ProgramCatalogRepository()
    embedder = embedder or GeminiEmbedder()
    enrich = enrich or _enrich

    existing = repository.get_program_content_hashes()

    prepared = []
    for program_id, canonical_name in source_programs():
        if not program_id:
            continue
        aliases_text, field = enrich(program_id)
        embed_input = _embed_input(canonical_name, aliases_text)
        content_hash = chunk_content_hash(embed_input)
        prepared.append((program_id, canonical_name, aliases_text, field, embed_input, content_hash))

    to_embed = [(p[0], p[4]) for p in prepared if existing.get(p[0]) != p[5]]
    vectors = {}
    if to_embed:
        embeddings = embedder.embed([t for _, t in to_embed], task_type="RETRIEVAL_DOCUMENT")
        vectors = {pid: emb for (pid, _), emb in zip(to_embed, embeddings)}

    embedded = reused = 0
    for program_id, canonical_name, aliases_text, field, embed_input, content_hash in prepared:
        emb = vectors.get(program_id)
        if emb is None:
            reused += 1
            continue
        repository.upsert_program(
            program_id=program_id, canonical_name=canonical_name,
            aliases_text=aliases_text, field=field, embed_input=embed_input,
            content_hash=content_hash, embedding=emb, source="canonical",
        )
        embedded += 1

    logger.info("major catalog build: total=%d embedded=%d reused=%d",
                len(prepared), embedded, reused)
    return CatalogBuildReport(total=len(prepared), embedded=embedded, reused=reused)
