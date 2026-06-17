import observability.run_trace as rt
from state import AgentState
from services.tracing.agent_tracer import traced


class _Repo:
    def start_event(self, run_id, stage, sequence):
        return 1

    def complete_event(self, event_id, output_json):
        return None

    def fail_event(self, event_id, error_text):
        return None


class _FakeSpan:
    def __init__(self, rec, name):
        self.rec, self.name = rec, name

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, **kwargs):
        self.rec["updates"].append((self.name, kwargs))


class _FakeLangfuse:
    def __init__(self, rec):
        self.rec = rec

    def start_as_current_span(self, *, name, metadata=None, **kwargs):
        self.rec["spans"].append(name)
        return _FakeSpan(self.rec, name)


def test_traced_opens_langfuse_stage_span_and_sets_output(monkeypatch):
    rec = {"spans": [], "updates": []}
    monkeypatch.setattr(rt, "get_langfuse", lambda: _FakeLangfuse(rec))

    def agent(state):
        state.user_query = "done"
        return state

    extractor = lambda result, state: {"snapshot": result.user_query}
    wrapped = traced("profile", 0, extractor, repository=_Repo())(agent)
    wrapped(AgentState(user_query="start", trace_run_id=7))

    assert rec["spans"] == ["profile"]
    assert ("profile", {"output": {"snapshot": "done"}}) in rec["updates"]


def test_langfuse_failure_does_not_break_agent(monkeypatch):
    class _Boom:
        def start_as_current_span(self, **kwargs):
            raise RuntimeError("langfuse down")

    monkeypatch.setattr(rt, "get_langfuse", lambda: _Boom())

    def agent(state):
        state.user_query = "ran-anyway"
        return state

    wrapped = traced("reason", 3, lambda r, s: {}, repository=_Repo())(agent)
    result = wrapped(AgentState(user_query="x", trace_run_id=1))
    assert result.user_query == "ran-anyway"
