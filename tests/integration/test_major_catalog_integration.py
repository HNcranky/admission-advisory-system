import pytest

from ingestion.storage.db_connection import get_connection


def _db_or_skip():
    try:
        conn = get_connection()
    except Exception:
        pytest.skip("Postgres not available")
    return conn


def test_program_catalog_table_exists():
    conn = _db_or_skip()
    try:
        cur = conn.cursor()
        cur.execute("SELECT to_regclass('public.program_catalog_embeddings')")
        assert cur.fetchone()[0] is not None, "run: python -m db.setup_db (migration 015)"
    finally:
        conn.close()


from services.profile.major_catalog_repository import ProgramCatalogRepository


def test_upsert_and_vector_search_roundtrip():
    _db_or_skip().close()
    repo = ProgramCatalogRepository()
    vec = [0.0] * 768
    vec[0] = 1.0
    repo.upsert_program(
        program_id="__test_cs__", canonical_name="Khoa học Máy tính",
        aliases_text="computer science, cntt", field="technology",
        embed_input="Khoa học Máy tính. computer science, cntt",
        content_hash="hash_test_cs", embedding=vec, source="canonical",
    )
    hits = repo.vector_search_programs(vec, limit=5)
    ids = [h.program_id for h in hits]
    assert "__test_cs__" in ids
    top = next(h for h in hits if h.program_id == "__test_cs__")
    assert top.score > 0.99  # cùng vector → cosine ~1

    hashes = repo.get_program_content_hashes()
    assert hashes.get("__test_cs__") == "hash_test_cs"

    # cleanup
    repo.delete_program("__test_cs__")
