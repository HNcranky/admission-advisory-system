import contextlib

from observability import run_trace


def test_turn_trace_yields_none_when_disabled(monkeypatch):
    monkeypatch.setattr(run_trace, "get_langfuse", lambda: None)
    with run_trace.turn_trace("tok:1", "tok", "hello") as span:
        assert span is None


def test_turn_trace_opens_and_closes_span(monkeypatch):
    events = []

    class FakeSpan:
        def update_trace(self, **kw): events.append(("update_trace", kw))

    class FakeCM:
        def __enter__(self): events.append(("enter", None)); return FakeSpan()
        def __exit__(self, *a): events.append(("exit", None)); return False

    class FakeClient:
        def create_trace_id(self, seed=None): return f"tid-{seed}"
        def start_as_current_span(self, **kw):
            events.append(("start", kw)); return FakeCM()

    monkeypatch.setattr(run_trace, "get_langfuse", lambda: FakeClient())
    with run_trace.turn_trace("tok:3", "tok", "học phí UET?") as span:
        assert span is not None
    names = [e[0] for e in events]
    assert names == ["start", "enter", "update_trace", "exit"]
    start_kw = events[0][1]
    assert start_kw["trace_context"] == {"trace_id": "tid-tok:3"}


def test_turn_trace_swallows_open_error(monkeypatch):
    class BoomClient:
        def create_trace_id(self, seed=None): raise RuntimeError("boom")
    monkeypatch.setattr(run_trace, "get_langfuse", lambda: BoomClient())
    with run_trace.turn_trace("tok:1", "tok", "x") as span:
        assert span is None  # degraded, no raise
