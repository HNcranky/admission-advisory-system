import json

from ingestion.knowledge.national_sources import load_national_sources


def test_loads_curated_rows(tmp_path):
    p = tmp_path / "n.json"
    p.write_text(json.dumps([
        {"url": "https://datafiles.chinhphu.vn/a.pdf", "title": "A"},
        {"url": "https://datafiles.chinhphu.vn/b.pdf", "title": "B"},
    ]), encoding="utf-8")
    rows = load_national_sources(p)
    assert [r["url"] for r in rows] == [
        "https://datafiles.chinhphu.vn/a.pdf",
        "https://datafiles.chinhphu.vn/b.pdf",
    ]


def test_skips_rows_without_url(tmp_path):
    p = tmp_path / "n.json"
    p.write_text(json.dumps([
        {"title": "no url"},
        {"url": "https://datafiles.chinhphu.vn/ok.pdf", "title": "ok"},
    ]), encoding="utf-8")
    rows = load_national_sources(p)
    assert [r["url"] for r in rows] == ["https://datafiles.chinhphu.vn/ok.pdf"]


def test_missing_file_returns_empty(tmp_path):
    assert load_national_sources(tmp_path / "nope.json") == []


def test_default_seed_file_is_valid():
    # the committed seed file loads and every row has a url
    rows = load_national_sources()
    assert len(rows) >= 1
    assert all(r.get("url") for r in rows)
