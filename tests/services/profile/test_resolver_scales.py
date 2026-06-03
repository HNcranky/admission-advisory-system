from services.profile.major_catalog_repository import ProgramCandidate
from services.profile.major_resolver import resolve_majors


class FakeEmbedder:
    def embed(self, texts, task_type="RETRIEVAL_QUERY"):
        return [[0.3] * 768 for _ in texts]


class FakeRepo:
    def __init__(self, candidates):
        self._candidates = candidates

    def vector_search_programs(self, embedding, limit=8):
        return self._candidates[:limit]


def test_brand_new_program_id_resolves_without_code_change():
    """Ngành mới 'quantum_computing' chỉ tồn tại trong catalog (DB), KHÔNG nằm
    trong bất kỳ prompt/map hardcode nào — resolver vẫn trả về được."""
    # Phrase deliberately avoids any existing programs.json alias so Tier1
    # returns nothing and resolution must come from the catalog (Tier2).
    repo = FakeRepo([ProgramCandidate("quantum_computing", "Máy tính Lượng tử", 0.88)])
    result = resolve_majors("em thích máy tính lượng tử và vật lý",
                            repository=repo, embedder=FakeEmbedder())
    assert result == ["quantum_computing"]
