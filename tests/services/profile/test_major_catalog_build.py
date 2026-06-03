from services.profile.major_catalog import build_major_catalog, _embed_input
from services.knowledge.repository import chunk_content_hash


class FakeEmbedder:
    def __init__(self):
        self.embedded_texts = []

    def embed(self, texts, task_type="RETRIEVAL_DOCUMENT"):
        self.embedded_texts.extend(texts)
        return [[0.1] * 768 for _ in texts]


class FakeBuildRepo:
    def __init__(self, existing=None):
        self._existing = existing or {}
        self.upserts = []

    def get_program_content_hashes(self):
        return dict(self._existing)

    def upsert_program(self, **kwargs):
        self.upserts.append(kwargs)


def _no_enrich(program_id):
    return ("", None)


def test_build_embeds_new_programs():
    rows = [("computer_science", "Khoa học Máy tính"),
            ("software_engineering", "Kỹ thuật Phần mềm")]
    repo, emb = FakeBuildRepo(), FakeEmbedder()
    report = build_major_catalog(source_programs=lambda: rows, repository=repo,
                                 embedder=emb, enrich=_no_enrich)
    assert report.total == 2
    assert report.embedded == 2
    assert report.reused == 0
    assert len(repo.upserts) == 2
    assert len(emb.embedded_texts) == 2


def test_build_skips_unchanged_by_content_hash():
    rows = [("computer_science", "Khoa học Máy tính")]
    unchanged_hash = chunk_content_hash(_embed_input("Khoa học Máy tính", ""))
    repo = FakeBuildRepo(existing={"computer_science": unchanged_hash})
    emb = FakeEmbedder()
    report = build_major_catalog(source_programs=lambda: rows, repository=repo,
                                 embedder=emb, enrich=_no_enrich)
    assert report.embedded == 0
    assert report.reused == 1
    assert repo.upserts == []           # không upsert dòng không đổi
    assert emb.embedded_texts == []     # không gọi embed


def test_build_skips_rows_without_program_id():
    rows = [(None, "Không có id"), ("law", "Luật")]
    repo, emb = FakeBuildRepo(), FakeEmbedder()
    report = build_major_catalog(source_programs=lambda: rows, repository=repo,
                                 embedder=emb, enrich=_no_enrich)
    assert report.total == 1
    assert [u["program_id"] for u in repo.upserts] == ["law"]
