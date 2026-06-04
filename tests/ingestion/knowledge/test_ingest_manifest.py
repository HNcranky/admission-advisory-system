import ingestion.knowledge.ingest_manifest as mod
from ingestion.knowledge.crawler.manifest import (
    ManifestEntry,
    load_manifest,
    save_manifest,
)
from ingestion.knowledge.ingest_manifest import ingest_keep_entries
from ingestion.knowledge.pipeline import KnowledgeIngestResult


class FakePipe:
    def __init__(self, behavior):
        self.behavior = behavior          # url -> KnowledgeIngestResult | Exception
        self.calls = []

    def run_for_url(self, url, *, school, **kwargs):
        self.calls.append((url, school))
        outcome = self.behavior[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _entry(url, school="HUST", status="keep"):
    return ManifestEntry(school=school, url=url, status=status)


def _ok(url):
    return KnowledgeIngestResult(source_url=url, skipped=False)


def _skip(url):
    return KnowledgeIngestResult(source_url=url, skipped=True)


def test_only_keep_entries_are_ingested():
    entries = [
        _entry("https://a.vn/keep.pdf", status="keep"),
        _entry("https://a.vn/skip.pdf", status="skip"),
        _entry("https://a.vn/pending.pdf", status="pending"),
        _entry("https://a.vn/done.pdf", status="done"),
    ]
    pipe = FakePipe({"https://a.vn/keep.pdf": _ok("https://a.vn/keep.pdf")})
    ingest_keep_entries(entries, pipe)
    assert [u for u, _ in pipe.calls] == ["https://a.vn/keep.pdf"]


def test_success_sets_done_and_passes_entry_school():
    entries = [_entry("https://a.vn/k.pdf", school="NEU", status="keep")]
    pipe = FakePipe({"https://a.vn/k.pdf": _ok("https://a.vn/k.pdf")})
    results = ingest_keep_entries(entries, pipe)
    assert entries[0].status == "done"
    assert pipe.calls == [("https://a.vn/k.pdf", "NEU")]
    assert results == [("OK", "https://a.vn/k.pdf")]


def test_skip_unchanged_also_marks_done():
    entries = [_entry("https://a.vn/k.pdf", status="keep")]
    pipe = FakePipe({"https://a.vn/k.pdf": _skip("https://a.vn/k.pdf")})
    results = ingest_keep_entries(entries, pipe)
    assert entries[0].status == "done"
    assert results == [("SKIP", "https://a.vn/k.pdf")]


def test_failure_keeps_status_for_retry():
    entries = [_entry("https://a.vn/bad.pdf", status="keep")]
    pipe = FakePipe({"https://a.vn/bad.pdf": RuntimeError("boom")})
    results = ingest_keep_entries(entries, pipe)
    assert entries[0].status == "keep"        # not done → retried next run
    assert results == [("FAIL", "https://a.vn/bad.pdf")]


def test_main_ingests_keep_and_persists_status(tmp_path, monkeypatch, capsys):
    path = tmp_path / "manifest.json"
    save_manifest(path, [
        ManifestEntry(school="HUST", url="https://a.vn/k.pdf", status="keep"),
        ManifestEntry(school="HUST", url="https://a.vn/s.pdf", status="skip"),
    ])

    class FakePipeline:
        def run_for_url(self, url, *, school, **kwargs):
            return KnowledgeIngestResult(source_url=url, skipped=False)

    monkeypatch.setattr(mod, "KnowledgePipeline", lambda: FakePipeline())

    rc = mod._main(["--manifest", str(path)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "https://a.vn/k.pdf" in out
    assert "ok=1" in out
    after = {e.url: e.status for e in load_manifest(path)}
    assert after == {"https://a.vn/k.pdf": "done", "https://a.vn/s.pdf": "skip"}


def test_main_no_keep_entries_is_a_noop(tmp_path, monkeypatch, capsys):
    path = tmp_path / "manifest.json"
    save_manifest(path, [ManifestEntry(school="HUST", url="https://a.vn/p.pdf",
                                       status="pending")])

    def _boom():
        raise AssertionError("pipeline must not be built when nothing is kept")

    monkeypatch.setattr(mod, "KnowledgePipeline", _boom)

    rc = mod._main(["--manifest", str(path)])

    assert rc == 0
    assert "No entries with status=keep" in capsys.readouterr().out
