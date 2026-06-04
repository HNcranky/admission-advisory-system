import ingestion.knowledge.ingest_national as mod
from ingestion.knowledge.ingest_national import ingest_sources
from ingestion.knowledge.pipeline import KnowledgeIngestResult
from services.knowledge.scope import NATIONAL_SCHOOL, NATIONAL_DOCUMENT_TYPE


class FakePipe:
    def __init__(self, behavior):
        self.behavior = behavior          # url -> KnowledgeIngestResult | Exception
        self.calls = []

    def run_for_url(self, url, *, school, document_type=None, **kwargs):
        self.calls.append((url, school, document_type))
        outcome = self.behavior[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _ok(url):
    return KnowledgeIngestResult(source_url=url, skipped=False)


def _skip(url):
    return KnowledgeIngestResult(source_url=url, skipped=True)


def test_ingests_each_source_under_national_scope():
    sources = [{"url": "https://cp/a.pdf", "title": "A"},
               {"url": "https://cp/b.pdf", "title": "B"}]
    pipe = FakePipe({"https://cp/a.pdf": _ok("https://cp/a.pdf"),
                     "https://cp/b.pdf": _ok("https://cp/b.pdf")})
    results = ingest_sources(sources, pipe)
    assert pipe.calls == [
        ("https://cp/a.pdf", NATIONAL_SCHOOL, NATIONAL_DOCUMENT_TYPE),
        ("https://cp/b.pdf", NATIONAL_SCHOOL, NATIONAL_DOCUMENT_TYPE),
    ]
    assert results == [("OK", "https://cp/a.pdf"), ("OK", "https://cp/b.pdf")]


def test_unchanged_source_is_reported_skip():
    sources = [{"url": "https://cp/a.pdf", "title": "A"}]
    pipe = FakePipe({"https://cp/a.pdf": _skip("https://cp/a.pdf")})
    assert ingest_sources(sources, pipe) == [("SKIP", "https://cp/a.pdf")]


def test_one_failure_does_not_abort_the_batch():
    sources = [{"url": "https://cp/a.pdf", "title": "A"},
               {"url": "https://cp/bad.pdf", "title": "bad"},
               {"url": "https://cp/c.pdf", "title": "C"}]
    pipe = FakePipe({"https://cp/a.pdf": _ok("https://cp/a.pdf"),
                     "https://cp/bad.pdf": RuntimeError("boom"),
                     "https://cp/c.pdf": _ok("https://cp/c.pdf")})
    results = ingest_sources(sources, pipe)
    assert results == [("OK", "https://cp/a.pdf"),
                       ("FAIL", "https://cp/bad.pdf"),
                       ("OK", "https://cp/c.pdf")]


def test_main_ingests_sources_and_prints_summary(monkeypatch, capsys):
    monkeypatch.setattr(mod, "load_national_sources",
                        lambda path=None: [{"url": "https://cp/a.pdf", "title": "A"}])

    class FakePipeline:
        def run_for_url(self, url, *, school, document_type=None, **kwargs):
            return KnowledgeIngestResult(source_url=url, skipped=False)

    monkeypatch.setattr(mod, "KnowledgePipeline", lambda: FakePipeline())

    rc = mod._main([])

    out = capsys.readouterr().out
    assert rc == 0
    assert "https://cp/a.pdf" in out
    assert "ok=1" in out


def test_main_no_sources_is_a_noop(monkeypatch, capsys):
    monkeypatch.setattr(mod, "load_national_sources", lambda path=None: [])

    def _boom():
        raise AssertionError("pipeline must not be built when there are no sources")

    monkeypatch.setattr(mod, "KnowledgePipeline", _boom)

    rc = mod._main([])

    assert rc == 0
    assert "No national sources" in capsys.readouterr().out
