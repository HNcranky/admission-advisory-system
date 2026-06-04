from ingestion.knowledge.crawler.manifest import (
    ManifestEntry, load_manifest, merge_candidates, save_manifest, tag_relevance,
)
from ingestion.knowledge.crawler.pdf_crawler import CandidatePdf


def test_save_then_load_round_trip(tmp_path):
    path = tmp_path / "manifest.json"
    entries = [
        ManifestEntry(school="HUST", url="https://a.vn/de-an.pdf",
                      anchor_text="Đề án 2026", status="keep"),
    ]
    save_manifest(path, entries)
    loaded = load_manifest(path)
    assert loaded == entries


def test_load_missing_file_returns_empty(tmp_path):
    assert load_manifest(tmp_path / "nope.json") == []


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "data" / "knowledge" / "manifest.json"
    save_manifest(path, [])
    assert path.exists()


def test_relevance_high_on_anchor_keyword():
    assert tag_relevance("Đề án tuyển sinh 2026", "https://a.vn/x.pdf") == "high"


def test_relevance_high_on_url_keyword_no_accent():
    assert tag_relevance("", "https://a.vn/tuyen-sinh/chi-tieu.pdf") == "high"


def test_relevance_low_when_no_keyword():
    assert tag_relevance("Quyết định nhân sự", "https://a.vn/qd-123.pdf") == "low"


def test_merge_appends_new_as_pending_with_relevance():
    existing = [ManifestEntry(school="HUST", url="https://a.vn/old.pdf", status="keep")]
    cands = [CandidatePdf(school="HUST", url="https://a.vn/new.pdf",
                          anchor_text="Đề án tuyển sinh", found_on="https://a.vn/p")]
    merged = merge_candidates(existing, cands, discovered_at="2026-06-04")
    by = {m.url: m for m in merged}
    assert by["https://a.vn/old.pdf"].status == "keep"        # decision preserved
    assert by["https://a.vn/new.pdf"].status == "pending"
    assert by["https://a.vn/new.pdf"].relevance == "high"
    assert by["https://a.vn/new.pdf"].discovered_at == "2026-06-04"


def test_merge_keeps_decision_for_rediscovered_url():
    existing = [ManifestEntry(school="HUST", url="https://a.vn/x.pdf", status="skip")]
    cands = [CandidatePdf(school="HUST", url="https://a.vn/x.pdf",
                          anchor_text="x", found_on="y", size_bytes=999)]
    merged = merge_candidates(existing, cands, discovered_at="2026-06-04")
    assert len(merged) == 1
    assert merged[0].status == "skip"          # not reset to pending
    assert merged[0].size_bytes == 999         # metadata refreshed
