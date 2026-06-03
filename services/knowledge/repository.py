import hashlib
from contextlib import contextmanager

from services.knowledge.db import get_knowledge_db_connection
from services.knowledge.models import KnowledgeChunk, ScoredChunk, KnowledgeDocument


def chunk_content_hash(text: str) -> str:
    """Single source of truth for the embedding-reuse-map key (Plan 05)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_vector(raw) -> list[float]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [float(x) for x in raw]
    s = str(raw).strip().strip("[]")
    if not s:
        return []
    return [float(x) for x in s.split(",")]


def _vector_literal(embedding):
    if embedding is None:
        return None
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


@contextmanager
def _cursor(connection_factory, commit: bool = False):
    """Yield a cursor, guaranteeing commit/rollback and connection cleanup."""
    conn = connection_factory()
    try:
        cur = conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        conn.close()


# SELECT column order shared by the read methods (id is selected separately).
_CHUNK_COLUMNS = (
    "knowledge_document_id, school, program, year, document_type, "
    "topic, chunk_text, content_hash, source_url, span_start, span_end"
)


class KnowledgeChunkRepository:
    def __init__(self, connection_factory=get_knowledge_db_connection):
        self.connection_factory = connection_factory

    def upsert_chunk(self, chunk: KnowledgeChunk) -> int:
        with _cursor(self.connection_factory, commit=True) as cur:
            cur.execute(
                """
                INSERT INTO knowledge_chunks
                    (knowledge_document_id, school, program, year, document_type,
                     topic, chunk_text, content_hash, embedding, source_url, span_start, span_end)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s)
                ON CONFLICT (source_url, span_start, span_end) DO UPDATE SET
                    knowledge_document_id = EXCLUDED.knowledge_document_id,
                    school        = EXCLUDED.school,
                    program       = EXCLUDED.program,
                    year          = EXCLUDED.year,
                    document_type = EXCLUDED.document_type,
                    topic         = EXCLUDED.topic,
                    chunk_text    = EXCLUDED.chunk_text,
                    content_hash  = EXCLUDED.content_hash,
                    embedding     = EXCLUDED.embedding,
                    ingested_at   = NOW()
                RETURNING id
                """,
                (
                    chunk.knowledge_document_id,
                    chunk.school,
                    chunk.program,
                    chunk.year,
                    chunk.document_type,
                    chunk.topic,
                    chunk.chunk_text,
                    chunk.content_hash,
                    _vector_literal(chunk.embedding),
                    chunk.source_url,
                    chunk.span_start,
                    chunk.span_end,
                ),
            )
            chunk_id = cur.fetchone()[0]
        return chunk_id

    @staticmethod
    def _row_to_chunk(row) -> KnowledgeChunk:
        return KnowledgeChunk(
            knowledge_document_id=row[1],
            school=row[2],
            program=row[3],
            year=row[4],
            document_type=row[5],
            topic=row[6],
            chunk_text=row[7],
            content_hash=row[8],
            source_url=row[9],
            span_start=row[10],
            span_end=row[11],
        )

    def get_embedding_map_for_document(self, doc_id: int) -> dict[str, list[float]]:
        with _cursor(self.connection_factory) as cur:
            cur.execute(
                "SELECT chunk_text, embedding FROM knowledge_chunks "
                "WHERE knowledge_document_id = %s AND embedding IS NOT NULL",
                (doc_id,),
            )
            rows = cur.fetchall()
        return {
            chunk_content_hash(chunk_text): _parse_vector(embedding)
            for chunk_text, embedding in rows
        }

    def get_embeddings_for_hashes(self, hashes) -> dict[str, list[float]]:
        """Map content_hash -> embedding across the WHOLE corpus.

        Cross-document reuse: identical chunk text appearing in any document
        shares one embedding, so re-ingestion never re-embeds text already seen.
        """
        hashes = list(hashes)
        if not hashes:
            return {}
        with _cursor(self.connection_factory) as cur:
            cur.execute(
                "SELECT DISTINCT ON (content_hash) content_hash, embedding "
                "FROM knowledge_chunks "
                "WHERE content_hash = ANY(%s) AND embedding IS NOT NULL "
                "ORDER BY content_hash",
                (hashes,),
            )
            rows = cur.fetchall()
        return {h: _parse_vector(embedding) for h, embedding in rows}

    def delete_chunks_for_document(self, doc_id: int) -> int:
        with _cursor(self.connection_factory, commit=True) as cur:
            cur.execute(
                "DELETE FROM knowledge_chunks WHERE knowledge_document_id = %s",
                (doc_id,),
            )
            deleted = cur.rowcount
        return deleted

    def search_by_metadata(self, school, topic=None, limit=20):
        sql = f"SELECT id, {_CHUNK_COLUMNS} FROM knowledge_chunks WHERE school = %s"
        params = [school]
        if topic is not None:
            sql += " AND topic = %s"
            params.append(topic)
        sql += " ORDER BY id LIMIT %s"
        params.append(limit)
        with _cursor(self.connection_factory) as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [self._row_to_chunk(row) for row in rows]

    @staticmethod
    def _row_to_scored(row) -> ScoredChunk:
        return ScoredChunk(
            knowledge_document_id=row[1],
            school=row[2],
            program=row[3],
            year=row[4],
            document_type=row[5],
            topic=row[6],
            chunk_text=row[7],
            content_hash=row[8],
            source_url=row[9],
            span_start=row[10],
            span_end=row[11],
            score=row[12],
        )

    def vector_search(self, embedding, school=None, topic=None, limit=5):
        literal = _vector_literal(embedding)
        sql = (
            f"SELECT id, {_CHUNK_COLUMNS}, "
            "1 - (embedding <=> %s::vector) AS score "
            "FROM knowledge_chunks WHERE embedding IS NOT NULL"
        )
        params = [literal]
        if school is not None:
            sql += " AND school = %s"
            params.append(school)
        if topic is not None:
            sql += " AND topic = %s"
            params.append(topic)
        sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
        params.append(literal)
        params.append(limit)
        with _cursor(self.connection_factory) as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [self._row_to_scored(row) for row in rows]


class KnowledgeDocumentRepository:
    def __init__(self, connection_factory=get_knowledge_db_connection):
        self.connection_factory = connection_factory

    def get_document_by_url(self, url: str) -> KnowledgeDocument | None:
        with _cursor(self.connection_factory) as cur:
            cur.execute(
                "SELECT id, school, document_type, source_url, content_hash, raw_text "
                "FROM knowledge_documents WHERE source_url = %s",
                (url,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return KnowledgeDocument(
            id=row[0],
            school=row[1],
            document_type=row[2],
            source_url=row[3],
            content_hash=row[4],
            raw_text=row[5],
        )

    def get_or_create_document(self, doc: KnowledgeDocument) -> int:
        with _cursor(self.connection_factory, commit=True) as cur:
            cur.execute(
                """
                INSERT INTO knowledge_documents
                    (school, document_type, source_url, raw_text)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (source_url) DO UPDATE SET
                    school        = EXCLUDED.school,
                    document_type = EXCLUDED.document_type,
                    raw_text      = EXCLUDED.raw_text,
                    fetched_at    = NOW()
                RETURNING id
                """,
                (doc.school, doc.document_type, doc.source_url, doc.raw_text),
            )
            doc_id = cur.fetchone()[0]
        return doc_id

    def mark_ingested(self, doc_id: int, content_hash: str) -> None:
        with _cursor(self.connection_factory, commit=True) as cur:
            cur.execute(
                "UPDATE knowledge_documents "
                "SET content_hash = %s, ingested_at = NOW() WHERE id = %s",
                (content_hash, doc_id),
            )
