from ingestion.knowledge.pipeline import KnowledgePipeline, KnowledgeIngestResult
from ingestion.knowledge.registry.models import KnowledgeSource


class FakeRegistry:
    def __init__(self, sources):
        self._sources = sources

    def get_sources_by_school(self, school):
        return [s for s in self._sources if s.school == school]

    def all_sources(self):
        return list(self._sources)

    def schools(self):
        out = []
        for s in self._sources:
            if s.school not in out:
                out.append(s.school)
        return out


def _src(school, url):
    return KnowledgeSource(school=school, source_url=url,
                           document_type="tuition_page", topic="tuition")


def test_run_for_school_isolates_failing_source():
    sources = [_src("HUST", "https://ok"), _src("HUST", "https://boom")]
    pipe = KnowledgePipeline(registry=FakeRegistry(sources))

    def fake_run(source):
        if source.source_url == "https://boom":
            raise RuntimeError("fetch exploded")
        return KnowledgeIngestResult(source_url=source.source_url, skipped=False, chunks_total=2)

    pipe.run_for_source = fake_run

    results = pipe.run_for_school("HUST")

    # the good source still produced a result; the bad one was swallowed
    assert [r.source_url for r in results] == ["https://ok"]


def test_run_all_iterates_every_school():
    sources = [_src("HUST", "https://h"), _src("NEU", "https://n")]
    pipe = KnowledgePipeline(registry=FakeRegistry(sources))
    pipe.run_for_source = lambda s: KnowledgeIngestResult(source_url=s.source_url, skipped=False)

    results = pipe.run_all()

    assert {r.source_url for r in results} == {"https://h", "https://n"}
