"""Postgres-backed semantic cache for Knowledge QA answers.

Mirrors KnowledgeChunkRepository: injectable connection_factory, all DB access
via services.db.cursor. The row store/lookup half is added in Plan 02; this
module starts with the scope-key helpers and the version-stamping operations
that the invalidation strategy rests on.
"""
import json
from dataclasses import dataclass

from services.db import cursor as _cursor, vector_literal as _vector_literal
from services.knowledge.models import Citation, KnowledgeQAResult
from services.knowledge.scope import NATIONAL_SCHOOL


def _load_json(value):
    """psycopg2 decodes jsonb to a Python object by default; tolerate a raw
    string/bytes too (defensive — keeps unit fakes simple)."""
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value or {}


@dataclass
class CachedAnswer:
    answer: str
    citations: list
    confidence: float

    def to_result(self, from_cache: bool = False) -> KnowledgeQAResult:
        return KnowledgeQAResult(
            has_data=True,
            answer=self.answer,
            citations=list(self.citations),
            confidence=self.confidence,
            from_cache=from_cache,
        )


def scope_key_for(school: str, topic: str | None) -> str:
    """One scope_key for a (school, topic). NULL/empty topic → wildcard '*'.

    Both the read side (QACacheRepository.scope_keys) and the ingest bump derive
    their keys through this single helper, so they are guaranteed to agree.
    """
    return f"s:{school}|t:{topic if topic else '*'}"


class QACacheRepository:
    def __init__(self, connection_factory=None):
        # Imported lazily to mirror the knowledge repos and avoid importing the
        # DB layer at module import time.
        if connection_factory is None:
            from services.knowledge.db import get_knowledge_db_connection
            connection_factory = get_knowledge_db_connection
        self.connection_factory = connection_factory

    @staticmethod
    def scope_keys(school: str, topic: str) -> list[str]:
        """The four corpus scopes a concrete (school, topic) answer depends on:
        the school's own topic chunks, the school's wildcard (NULL-topic) docs,
        and the national-scope (MOET) equivalents merged into every school
        answer (qa_service._augment_with_national)."""
        return [
            scope_key_for(school, topic),
            scope_key_for(school, None),
            scope_key_for(NATIONAL_SCHOOL, topic),
            scope_key_for(NATIONAL_SCHOOL, None),
        ]

    def current_versions(self, scope_keys) -> dict[str, int]:
        keys = list(scope_keys)
        if not keys:
            return {}
        with _cursor(self.connection_factory) as cur:
            cur.execute(
                "SELECT scope_key, version FROM knowledge_qa_cache_version "
                "WHERE scope_key = ANY(%s)",
                (keys,),
            )
            rows = cur.fetchall()
        found = {k: int(v) for k, v in rows}
        return {k: found.get(k, 0) for k in keys}

    def bump_version(self, scope_key: str) -> None:
        with _cursor(self.connection_factory, commit=True) as cur:
            cur.execute(
                """
                INSERT INTO knowledge_qa_cache_version (scope_key)
                VALUES (%s)
                ON CONFLICT (scope_key) DO UPDATE SET
                    version = knowledge_qa_cache_version.version + 1,
                    bumped_at = NOW()
                """,
                (scope_key,),
            )

    def store(self, school, topic, question, embedding, result,
              dep_versions, ttl_days) -> None:
        answer_json = {
            "answer": result.answer or "",
            "citations": [
                {"source_url": c.source_url, "chunk_text": c.chunk_text}
                for c in result.citations
            ],
            "confidence": result.confidence,
        }
        with _cursor(self.connection_factory, commit=True) as cur:
            cur.execute(
                """
                INSERT INTO knowledge_qa_cache
                    (school, topic, question, embedding, answer_json,
                     confidence, dep_versions, expires_at)
                VALUES (%s, %s, %s, %s::vector, %s::jsonb, %s, %s::jsonb,
                        NOW() + make_interval(days => %s))
                """,
                (
                    school, topic, question, _vector_literal(embedding),
                    json.dumps(answer_json, ensure_ascii=False),
                    result.confidence,
                    json.dumps(dep_versions, ensure_ascii=False),
                    ttl_days,
                ),
            )

    def lookup(self, embedding, school, topic, threshold) -> "CachedAnswer | None":
        literal = _vector_literal(embedding)
        with _cursor(self.connection_factory) as cur:
            cur.execute(
                """
                SELECT answer_json, confidence, dep_versions,
                       1 - (embedding <=> %s::vector) AS score
                FROM knowledge_qa_cache
                WHERE school = %s AND topic = %s AND expires_at > NOW()
                ORDER BY embedding <=> %s::vector
                LIMIT 1
                """,
                (literal, school, topic, literal),
            )
            row = cur.fetchone()
        if row is None:
            return None
        answer_json, confidence, dep_versions, score = row
        if score is None or float(score) < threshold:
            return None
        stored = {k: int(v) for k, v in _load_json(dep_versions).items()}
        current = self.current_versions(self.scope_keys(school, topic))
        if stored != current:
            return None
        data = _load_json(answer_json)
        citations = [
            Citation(source_url=c.get("source_url", ""), chunk_text=c.get("chunk_text", ""))
            for c in data.get("citations", [])
        ]
        return CachedAnswer(
            answer=str(data.get("answer") or ""),
            citations=citations,
            confidence=float(confidence),
        )
