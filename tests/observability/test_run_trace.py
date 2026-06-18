import observability.run_trace as rt


class _FakeSpan:
    def __init__(self, recorder, name):
        self.recorder = recorder
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.recorder["closed"].append(self.name)
        return False

    def update(self, **kwargs):
        self.recorder["updates"].append((self.name, kwargs))

    def update_trace(self, **kwargs):
        self.recorder["trace"].append(kwargs)


class _FakeLangfuse:
    def __init__(self, recorder):
        self.recorder = recorder

    def create_trace_id(self, *, seed=None):
        return "trace-" + str(seed)

    def start_as_current_span(self, *, name, input=None, trace_context=None, metadata=None):
        self.recorder["spans"].append(
            {"name": name, "input": input, "trace_context": trace_context}
        )
        return _FakeSpan(self.recorder, name)

    def start_as_current_generation(self, *, name, model=None, input=None,
                                    model_parameters=None, metadata=None, prompt=None):
        self.recorder["generations"].append(
            {"name": name, "model": model, "input": input, "prompt": prompt}
        )
        return _FakeSpan(self.recorder, "gen:" + name)


def _recorder():
    return {"spans": [], "generations": [], "updates": [], "trace": [], "closed": []}


def test_helpers_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(rt, "get_langfuse", lambda: None)
    with rt.advisory_run_trace(1, "sess", "hi") as span:
        assert span is None
        with rt.stage_span("profile", 0) as s:
            assert s is None
            rt.set_span_output(s, {"x": 1})  # must not raise
    rt.record_generation(object(), object())  # must not raise


def test_advisory_run_trace_sets_session_and_trace_id(monkeypatch):
    rec = _recorder()
    monkeypatch.setattr(rt, "get_langfuse", lambda: _FakeLangfuse(rec))
    with rt.advisory_run_trace(7, "sess-abc", "em duoc 27 diem", intent="advisory"):
        pass
    assert rec["spans"][0]["name"] == "advisory-run"
    assert rec["spans"][0]["trace_context"] == {"trace_id": "trace-7"}
    assert rec["trace"][0]["session_id"] == "sess-abc"
    assert "advisory-run" in rec["closed"]


def test_stage_span_emits_named_span_and_output(monkeypatch):
    rec = _recorder()
    monkeypatch.setattr(rt, "get_langfuse", lambda: _FakeLangfuse(rec))
    with rt.stage_span("reason", 3) as span:
        rt.set_span_output(span, {"count": 2})
    assert rec["spans"][0]["name"] == "reason"
    assert ("reason", {"output": {"count": 2}}) in rec["updates"]


def test_record_generation_includes_usage_and_metadata(monkeypatch):
    rec = _recorder()
    monkeypatch.setattr(rt, "get_langfuse", lambda: _FakeLangfuse(rec))

    class _Req:
        agent_name = "reasoning_agent"
        task_type = "reason"
        system_prompt = "sys"
        user_prompt = "usr"
        temperature = 0.0

    class _Res:
        model = "gemini-2.5-flash-lite"
        content = "answer"
        failure_type = None

    rt.record_generation(
        _Req(), _Res(), usage={"input": 10, "output": 5, "total": 15},
        latency_ms=12.5, attempt=0, used_fallback=False,
    )
    assert rec["generations"][0]["name"] == "reasoning_agent"
    assert rec["generations"][0]["model"] == "gemini-2.5-flash-lite"
    gen_update = [u for u in rec["updates"] if u[0] == "gen:reasoning_agent"]
    assert gen_update, "generation should be updated with output/usage"
    payload = gen_update[0][1]
    assert payload["usage_details"] == {"input": 10, "output": 5, "total": 15}
    assert payload["output"] == "answer"


def test_errors_are_swallowed(monkeypatch):
    class _Boom:
        def create_trace_id(self, *, seed=None):
            raise RuntimeError("langfuse down")

        def start_as_current_span(self, **kwargs):
            raise RuntimeError("langfuse down")

        def start_as_current_generation(self, **kwargs):
            raise RuntimeError("langfuse down")

    monkeypatch.setattr(rt, "get_langfuse", lambda: _Boom())
    # None of these may raise:
    with rt.advisory_run_trace(1, "s", "hi") as span:
        assert span is None
        with rt.stage_span("profile", 0) as s:
            assert s is None
    rt.record_generation(object(), object())


def test_record_generation_forwards_prompt_handle(monkeypatch):
    rec = _recorder()
    monkeypatch.setattr(rt, "get_langfuse", lambda: _FakeLangfuse(rec))

    class _Req:
        agent_name = "intent_router"
        task_type = "intent_classification"
        system_prompt = "sys"
        user_prompt = "usr"
        temperature = 0.0

    class _Res:
        model = "gemini-2.5-flash-lite"
        content = "answer"
        failure_type = None

    handle = object()
    rt.record_generation(_Req(), _Res(), prompt=handle)
    assert rec["generations"][0]["prompt"] is handle


def test_record_generation_prompt_defaults_none(monkeypatch):
    rec = _recorder()
    monkeypatch.setattr(rt, "get_langfuse", lambda: _FakeLangfuse(rec))

    class _Req:
        agent_name = "intent_router"
        task_type = "t"
        system_prompt = "sys"
        user_prompt = "usr"
        temperature = 0.0

    class _Res:
        model = "m"
        content = "a"
        failure_type = None

    rt.record_generation(_Req(), _Res())
    assert rec["generations"][0]["prompt"] is None
