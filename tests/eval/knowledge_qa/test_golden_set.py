from pathlib import Path

from eval.knowledge_qa.golden_set import DEFAULT_GOLDEN_PATH, load_golden_set
from eval.knowledge_qa.models import GoldenCase


def test_loads_seed_fixture():
    cases = load_golden_set()

    assert len(cases) >= 30
    assert all(isinstance(c, GoldenCase) for c in cases)

    answerable = next(c for c in cases if c.id == "neu-total-quota")
    assert answerable.abstain is False
    assert answerable.expected_source_ids == [2]
    assert answerable.expected_answer_points

    abstain = next(c for c in cases if c.id == "hust-free-dorm-abstain")
    assert abstain.abstain is True
    assert abstain.expected_answer_points == []


def test_default_path_points_at_packaged_fixture():
    assert DEFAULT_GOLDEN_PATH == Path(__file__).resolve().parents[3] / "eval" / "knowledge_qa" / "golden_set.json"
