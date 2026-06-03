import pytest

from state import AgentState
from services.tracing.agent_tracer import traced


class FakeTraceRepo:
    def __init__(self, next_event_id=99):
        self.started = []
        self.completed = []
        self.failed = []
        self._next_id = next_event_id

    def start_event(self, run_id, stage, sequence):
        self.started.append((run_id, stage, sequence))
        return self._next_id

    def complete_event(self, event_id, output_json):
        self.completed.append((event_id, output_json))

    def fail_event(self, event_id, error_text):
        self.failed.append((event_id, error_text))


class ExplodingTraceRepo:
    def start_event(self, *a, **kw):
        raise RuntimeError("db down")

    def complete_event(self, *a, **kw):
        raise RuntimeError("db down")

    def fail_event(self, *a, **kw):
        raise RuntimeError("db down")


def test_traced_bypasses_when_trace_run_id_is_none():
    called_with = {}

    def agent(state):
        called_with["state"] = state
        state.user_query = "modified"
        return state

    wrapped = traced("profile", 0, lambda result, state: {})(agent)
    state = AgentState(user_query="hello", trace_run_id=None)

    result = wrapped(state)

    assert result.user_query == "modified"
    assert called_with["state"] is state


def test_traced_writes_start_then_complete_on_success():
    repo = FakeTraceRepo(next_event_id=42)

    def agent(state):
        state.user_query = "after"
        return state

    extractor = lambda result, state: {"snapshot": result.user_query}
    wrapped = traced("profile", 0, extractor, repository=repo)(agent)

    state = AgentState(user_query="before", trace_run_id=7)
    wrapped(state)

    assert repo.started == [(7, "profile", 0)]
    assert repo.completed == [(42, {"snapshot": "after"})]
    assert repo.failed == []


def test_traced_writes_fail_event_and_reraises_on_exception():
    repo = FakeTraceRepo(next_event_id=55)

    def agent(state):
        raise ValueError("bad input")

    wrapped = traced("retrieve", 1, lambda r, s: {}, repository=repo)(agent)

    state = AgentState(user_query="hi", trace_run_id=3)

    with pytest.raises(ValueError, match="bad input"):
        wrapped(state)

    assert repo.started == [(3, "retrieve", 1)]
    assert repo.completed == []
    assert len(repo.failed) == 1
    assert repo.failed[0][0] == 55
    assert "ValueError" in repo.failed[0][1]
    assert "bad input" in repo.failed[0][1]


def test_traced_swallows_extractor_error_and_marks_completed():
    repo = FakeTraceRepo(next_event_id=88)

    def agent(state):
        return state

    def broken_extractor(result, state):
        raise TypeError("not serializable")

    wrapped = traced("policy", 4, broken_extractor, repository=repo)(agent)

    state = AgentState(user_query="hi", trace_run_id=1)
    wrapped(state)

    assert repo.completed == [(88, {"_extractor_error": "TypeError('not serializable')"})]
    assert repo.failed == []


def test_traced_swallows_repo_errors_and_still_runs_agent():
    repo = ExplodingTraceRepo()

    def agent(state):
        state.user_query = "ran-anyway"
        return state

    wrapped = traced("profile", 0, lambda r, s: {}, repository=repo)(agent)

    state = AgentState(user_query="hi", trace_run_id=1)
    result = wrapped(state)

    assert result.user_query == "ran-anyway"


import logging

from services.tracing.agent_tracer import traced


class _NoopRepo:
    def start_event(self, run_id, stage, sequence):
        return 1

    def complete_event(self, event_id, output_json):
        return None

    def fail_event(self, event_id, error_text):
        return None


class _State:
    trace_run_id = "run-1"


def test_traced_logs_when_extractor_raises(caplog):
    def agent_fn(state):
        return {"ok": True}

    def bad_extractor(result, state):
        raise ValueError("boom")

    wrapped = traced("reason", 3, bad_extractor, repository=_NoopRepo())(agent_fn)

    with caplog.at_level(logging.WARNING, logger="services.tracing.agent_tracer"):
        result = wrapped(_State())

    assert result == {"ok": True}
    assert any(
        "extractor" in record.message and "reason" in record.message
        for record in caplog.records
    )
