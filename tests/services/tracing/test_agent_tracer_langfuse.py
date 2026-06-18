import types

from services.tracing import agent_tracer


def test_traced_opens_span_and_sets_output_without_repository(monkeypatch):
    calls = {"span_opened": False, "output": None}

    class FakeSpanCM:
        def __enter__(self): return "SPAN"
        def __exit__(self, *a): return False

    def fake_stage_span(stage, sequence, input_json=None):
        calls["span_opened"] = (stage, sequence, input_json)
        return FakeSpanCM()

    def fake_set_span_output(span, output_json):
        calls["output"] = (span, output_json)

    monkeypatch.setattr(agent_tracer, "stage_span", fake_stage_span)
    monkeypatch.setattr(agent_tracer, "set_span_output", fake_set_span_output)

    state = types.SimpleNamespace(trace_run_id=7, value=1)
    wrapped = agent_tracer.traced(
        "profile", 0,
        output_extractor=lambda result, st: {"out": result.value},
        input_extractor=lambda st: {"in": st.value},
    )(lambda st: types.SimpleNamespace(value=st.value + 1))

    result = wrapped(state)

    assert result.value == 2
    assert calls["span_opened"] == ("profile", 0, {"in": 1})
    assert calls["output"] == ("SPAN", {"out": 2})


def test_traced_noop_when_no_run_id(monkeypatch):
    monkeypatch.setattr(agent_tracer, "stage_span",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not span")))
    state = types.SimpleNamespace(trace_run_id=None)
    wrapped = agent_tracer.traced("profile", 0, lambda r, s: {})(lambda st: "ok")
    assert wrapped(state) == "ok"
