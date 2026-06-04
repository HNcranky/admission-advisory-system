from ingestion.knowledge.crawler.manifest import (
    ManifestEntry, load_manifest, save_manifest,
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
