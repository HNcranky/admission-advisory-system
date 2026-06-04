from ingestion.knowledge.crawl import build_manifest
from ingestion.knowledge.crawler.config import CrawlTarget
from ingestion.knowledge.crawler.manifest import ManifestEntry
from ingestion.knowledge.crawler.pdf_crawler import CandidatePdf


class _FakeDocRepo:
    def get_document_by_url(self, url):
        return None


def test_build_manifest_merges_crawl_output():
    targets = [CrawlTarget(school="HUST", seeds=["https://a.vn/s"],
                           allow_domains=["a.vn"])]

    def fake_crawl(target, sitemap=True):
        return [CandidatePdf(school="HUST", url="https://a.vn/de-an.pdf",
                             anchor_text="Đề án tuyển sinh", found_on="https://a.vn/s")]

    merged = build_manifest(targets, existing=[], crawl=fake_crawl,
                            doc_repo=_FakeDocRepo(), discovered_at="2026-06-04")
    assert len(merged) == 1
    assert merged[0].status == "pending"
    assert merged[0].relevance == "high"


def test_build_manifest_isolates_failing_target():
    targets = [
        CrawlTarget(school="HUST", seeds=["https://a.vn/s"], allow_domains=["a.vn"]),
        CrawlTarget(school="NEU", seeds=["https://b.vn/s"], allow_domains=["b.vn"]),
    ]

    def fake_crawl(target, sitemap=True):
        if target.school == "HUST":
            raise RuntimeError("boom")
        return [CandidatePdf(school="NEU", url="https://b.vn/x.pdf",
                             anchor_text="x", found_on="https://b.vn/s")]

    merged = build_manifest(targets, existing=[], crawl=fake_crawl,
                            doc_repo=_FakeDocRepo(), discovered_at="2026-06-04")
    assert {m.url for m in merged} == {"https://b.vn/x.pdf"}  # NEU survived HUST failure


def test_build_manifest_preserves_existing_decisions():
    targets = [CrawlTarget(school="HUST", seeds=["https://a.vn/s"], allow_domains=["a.vn"])]
    existing = [ManifestEntry(school="HUST", url="https://a.vn/de-an.pdf", status="skip")]

    def fake_crawl(target, sitemap=True):
        return [CandidatePdf(school="HUST", url="https://a.vn/de-an.pdf",
                             anchor_text="x", found_on="https://a.vn/s")]

    merged = build_manifest(targets, existing=existing, crawl=fake_crawl,
                            doc_repo=_FakeDocRepo(), discovered_at="2026-06-04")
    assert merged[0].status == "skip"


import ingestion.knowledge.crawl as crawl_mod


def test_main_passes_robots_gate_to_crawl_target(tmp_path, monkeypatch):
    captured = {}

    def fake_crawl_target(target, *, sitemap=True, allowed=None, delay=0.0):
        captured["allowed"] = allowed
        captured["delay"] = delay
        return []

    monkeypatch.setattr(crawl_mod, "crawl_target", fake_crawl_target)
    monkeypatch.setattr(crawl_mod, "load_targets",
                        lambda: [CrawlTarget(school="HUST", seeds=["https://a.vn/s"],
                                             allow_domains=["a.vn"])])

    class _DocRepo:
        def get_document_by_url(self, url):
            return None

    monkeypatch.setattr(
        "services.knowledge.repository.KnowledgeDocumentRepository",
        lambda: _DocRepo(),
    )

    rc = crawl_mod._main(["--school", "HUST", "--delay", "0.5",
                          "--manifest", str(tmp_path / "m.json")])

    assert rc == 0
    assert callable(captured["allowed"])         # robots gate wired by default
    assert captured["allowed"]("https://a.vn/x") in (True, False)
    assert captured["delay"] == 0.5
