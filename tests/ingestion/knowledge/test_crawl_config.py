import pytest
from pydantic import ValidationError

from ingestion.knowledge.crawler.config import CrawlTarget, load_targets


def test_load_targets_parses_seed():
    targets = load_targets()
    assert {t.school for t in targets} == {"HUST", "NEU", "VNU-UET"}
    hust = next(t for t in targets if t.school == "HUST")
    assert hust.seeds and all(s.startswith("http") for s in hust.seeds)
    assert hust.max_depth >= 1 and hust.max_pages >= 1


def test_unknown_school_rejected():
    with pytest.raises(ValidationError):
        CrawlTarget(school="FOO", seeds=["https://x"], allow_domains=["x"])


def test_defaults_applied():
    t = CrawlTarget(school="HUST", seeds=["https://hust.edu.vn"], allow_domains=["hust.edu.vn"])
    assert t.allow_path_prefixes == []
    assert t.max_depth == 2 and t.max_pages == 300
