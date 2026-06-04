from ingestion.knowledge.crawler.manifest import (
    ManifestEntry, load_manifest, save_manifest, tag_relevance,
)


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
