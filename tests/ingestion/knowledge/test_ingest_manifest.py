from ingestion.knowledge.crawler.manifest import ManifestEntry
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
