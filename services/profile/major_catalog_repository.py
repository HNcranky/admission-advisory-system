from dataclasses import dataclass
from typing import Dict, List, Optional

from ingestion.storage.db_connection import get_connection
from services.db import cursor as _cursor, vector_literal as _vector_literal


@dataclass
class ProgramCandidate:
    program_id: str
    canonical_name: str
    score: float


class ProgramCatalogRepository:
    def __init__(self, connection_factory=get_connection):
        self.connection_factory = connection_factory

    def upsert_program(self, *, program_id, canonical_name, aliases_text, field,
                       embed_input, content_hash, embedding, source="canonical") -> None:
        with _cursor(self.connection_factory, commit=True) as cur:
            cur.execute(
                """
                INSERT INTO program_catalog_embeddings
                    (program_id, canonical_name, aliases_text, field,
                     embed_input, content_hash, embedding, source, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s, NOW())
                ON CONFLICT (program_id) DO UPDATE SET
                    canonical_name = EXCLUDED.canonical_name,
                    aliases_text   = EXCLUDED.aliases_text,
                    field          = EXCLUDED.field,
                    embed_input    = EXCLUDED.embed_input,
                    content_hash   = EXCLUDED.content_hash,
                    embedding      = EXCLUDED.embedding,
                    source         = EXCLUDED.source,
                    updated_at     = NOW()
                """,
                (program_id, canonical_name, aliases_text, field,
                 embed_input, content_hash, _vector_literal(embedding), source),
            )

    def get_program_content_hashes(self) -> Dict[str, str]:
        """{program_id: content_hash} cho các dòng đã có embedding (để skip re-embed)."""
        with _cursor(self.connection_factory) as cur:
            cur.execute(
                "SELECT program_id, content_hash FROM program_catalog_embeddings "
                "WHERE embedding IS NOT NULL"
            )
            return {row[0]: row[1] for row in cur.fetchall()}

    def vector_search_programs(self, embedding, limit: int = 8) -> List[ProgramCandidate]:
        literal = _vector_literal(embedding)
        with _cursor(self.connection_factory) as cur:
            cur.execute(
                """
                SELECT program_id, canonical_name,
                       1 - (embedding <=> %s::vector) AS score
                FROM program_catalog_embeddings
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (literal, literal, limit),
            )
            return [ProgramCandidate(r[0], r[1], float(r[2])) for r in cur.fetchall()]

    def delete_program(self, program_id: str) -> None:
        with _cursor(self.connection_factory, commit=True) as cur:
            cur.execute(
                "DELETE FROM program_catalog_embeddings WHERE program_id = %s",
                (program_id,),
            )

    def count(self) -> int:
        with _cursor(self.connection_factory) as cur:
            cur.execute("SELECT COUNT(*) FROM program_catalog_embeddings")
            return cur.fetchone()[0]
