"""The synthetic conflict scenarios exercise the deterministic conflict service
with no LLM and no database, so they belong in the normal suite. Detection must
be exact: every injected conflict found, no agreeing control flagged."""

from types import SimpleNamespace

import pytest

from eval.conflict.run import _detect, _resolve
from eval.conflict.scenarios import SCENARIOS


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.key)
def test_detection_matches_ground_truth(scenario):
    detected = len(_detect(scenario)) > 0
    assert detected == scenario.should_conflict


def test_decision_changing_cutoff_is_left_unresolved():
    scenario = next(s for s in SCENARIOS if s.key == "cutoff_decision_changing")
    record = _detect(scenario)[0]
    status, _axes = _resolve(scenario, record)
    assert status == "unresolved"


def test_trust_split_quota_resolves_to_higher_trust():
    scenario = next(s for s in SCENARIOS if s.key == "quota_120_vs_140_trust_split")
    record = _detect(scenario)[0]
    status, axes = _resolve(scenario, record)
    assert status == "resolved"
    assert "trust_level" in axes
