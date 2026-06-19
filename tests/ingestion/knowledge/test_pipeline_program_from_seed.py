from ingestion.knowledge.pipeline import KnowledgePipeline
from ingestion.knowledge.registry.models import KnowledgeSource


# HTML with a HUST-style breadcrumb ("Ky thuat O to") + an <h2> section.
PAGE = (
    b"<html><head><title>T</title></head><body><div class='container'>"
    b"<ol class='breadcrumb'><li class='breadcrumb-item active'>Ky thuat O to</li></ol>"
    b"<section><h2 class='sec-title'>Co hoi viec lam</h2><p>Ky su van hanh.</p></section>"
    b"</div></body></html>"
)


class FakeFetch:
    def __init__(self, content):
        self.raw_content = content
        self.content_type = "text/html"
        self.content_hash = "h1"


class FakeDocRepo:
    def __init__(self):
        self.marked = []

    def get_document_by_url(self, url):
        return None

    def get_or_create_document(self, doc):
        return 1

    def mark_ingested(self, doc_id, content_hash):
        self.marked.append((doc_id, content_hash))


class FakeChunkRepo:
    def __init__(self):
        self.upserts = []

    def get_embeddings_for_hashes(self, hashes):
        return {}

    def delete_chunks_for_document(self, doc_id):
        return 0

    def upsert_chunk(self, chunk):
        self.upserts.append(chunk)
        return len(self.upserts)


class FakeEmbedder:
    def embed(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeCache:
    def bump_version(self, key):
        return None


def _pipeline(chunk_repo):
    return KnowledgePipeline(
        registry=None, embedder=FakeEmbedder(), doc_repo=FakeDocRepo(),
        chunk_repo=chunk_repo, fetch=lambda u: FakeFetch(PAGE),
        cache_repo=FakeCache(),
    )


def _source(program):
    return KnowledgeSource(
        school="HUST", source_url="https://x/ky-thuat-o-to",
        document_type="program_overview_page", topic="program_overview",
        chunk_strategy="by_section", program=program, selector="div.container",
    )


def test_seed_program_wins_over_breadcrumb():
    chunk_repo = FakeChunkRepo()
    _pipeline(chunk_repo).run_for_source(_source(program="Kỹ thuật Ô tô (canonical)"))
    assert chunk_repo.upserts, "expected chunks"
    assert all(c.program == "Kỹ thuật Ô tô (canonical)" for c in chunk_repo.upserts)
    # header uses the seed program, not the breadcrumb
    assert chunk_repo.upserts[0].chunk_text.startswith("Kỹ thuật Ô tô (canonical) — ")


def test_breadcrumb_used_when_seed_program_absent():
    chunk_repo = FakeChunkRepo()
    _pipeline(chunk_repo).run_for_source(_source(program=None))
    assert chunk_repo.upserts
    assert all(c.program == "Ky thuat O to" for c in chunk_repo.upserts)
    assert chunk_repo.upserts[0].chunk_text.startswith("Ky thuat O to — ")
