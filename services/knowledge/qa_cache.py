"""Postgres-backed semantic cache for Knowledge QA answers.

Mirrors KnowledgeChunkRepository: injectable connection_factory, all DB access
via services.db.cursor. The row store/lookup half is added in Plan 02; this
module starts with the scope-key helpers and the version-stamping operations
that the invalidation strategy rests on.
"""
from services.db import cursor as _cursor
from services.knowledge.scope import NATIONAL_SCHOOL


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
