from ingestion.knowledge.registry.knowledge_registry import KnowledgeRegistry
from services.knowledge.db import get_knowledge_db_connection


def collect_counts(connection_factory=get_knowledge_db_connection):
    conn = connection_factory()
    cur = conn.cursor()
    cur.execute(
        "SELECT school, topic, COUNT(*) FROM knowledge_chunks "
        "GROUP BY school, topic ORDER BY school, topic"
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [(r[0], r[1], r[2]) for r in rows]


def count_null_embeddings(connection_factory=get_knowledge_db_connection) -> int:
    conn = connection_factory()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM knowledge_chunks WHERE embedding IS NULL")
    n = cur.fetchone()[0]
    cur.close()
    conn.close()
    return n


def find_missing_schools(registry_schools, counts) -> list:
    present = {school for school, _topic, count in counts if count > 0}
    return [s for s in registry_schools if s not in present]


def main(connection_factory=get_knowledge_db_connection, registry=None) -> int:
    registry = registry or KnowledgeRegistry()
    counts = collect_counts(connection_factory)

    print("Chunk counts per school/topic:")
    for school, topic, count in counts:
        print(f"  {school:12} {(topic or '-'):22} {count}")

    nulls = count_null_embeddings(connection_factory)
    if nulls:
        print(f"WARNING: {nulls} chunk(s) have NULL embedding")

    missing = find_missing_schools(registry.schools(), counts)
    if missing:
        print(f"MISSING DATA for schools: {', '.join(missing)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
