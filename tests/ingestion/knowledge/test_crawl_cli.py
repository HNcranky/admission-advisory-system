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
