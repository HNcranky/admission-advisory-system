# Slice 06: `conflict_agent` 2 pha (1 call thay vì N)

> Part of **Sprint 1 — LLM efficiency**. Spec: `docs/superpowers/specs/2026-06-10-sprint1-llm-efficiency-design.md`
> REQUIRED SUB-SKILL: superpowers:subagent-driven-development / superpowers:executing-plans. Slice này = một commit. **Phụ thuộc: 05.**

**Goal:** `conflict_agent` gom mọi quota conflict *indecisive* thành **một** call batch; `resolve()` nhận callback **tra cứu** thay vì callback LLM ⇒ `resolve()`/`resolve_cutoff_conflict()` không đổi.

**Files:**
- Modify: `agents/conflict_agent.py` (imports + hàm `conflict_agent`)
- Test: `tests/agents/test_conflict_agent.py`

---

- [ ] **Step 1: Write/Update tests**

(a) **Cập nhật** `test_conflict_agent_resolves_via_llm_tiebreaker` — monkeypatch hàm batch thay vì per-conflict. Thay nguyên thân hàm:

```python
def test_conflict_agent_resolves_via_llm_tiebreaker(monkeypatch):
    class _Gateway:
        def is_available(self):
            return True

    monkeypatch.setattr(conflict_agent_module, "build_default_gateway", lambda: _Gateway())

    def fake_batch(pairs, gateway):
        return {
            record.conflict_key: {
                "confidence": "high",
                "chosen_source_url": report.ranked_options[0].source_url,
                "rationale": "nguon dang tin nhat",
            }
            for record, report in pairs
        }

    monkeypatch.setattr(conflict_agent_module, "batch_interpret_conflict_tiebreak", fake_batch)

    state = conflict_agent(_conflicting_state())

    assert any(o.used_llm_tiebreaker and o.status == "resolved" for o in state.resolution_outcomes)
```

(b) **Thêm** test khẳng định batching = đúng MỘT call cho NHIỀU conflict (dùng batch function thật + counting gateway):

```python
import json


def _indecisive_candidate(program_id, source_url, quota):
    return CandidateProgram(
        candidate_id=f"hust:2026:{program_id}:thpt_score",
        school_id="hust", school_name="HUST", admission_year=2026,
        program_id=program_id, program_name=program_id.upper(),
        admission_method="thpt_score", quota={"value": quota},
        evidence=[Evidence(source_url=source_url, school_name="HUST",
                           admission_year=2026, field_name="quota", trust_level=5)],
    )


def test_conflict_agent_batches_indecisive_into_single_llm_call(monkeypatch):
    calls = []

    class _CountingGateway:
        def is_available(self):
            return True

        def run(self, request):
            calls.append(request)
            payload = json.loads(request.user_prompt)
            decisions = [
                {"conflict_key": c["conflict_key"], "confidence": "high",
                 "chosen_source_url": c["options"][0]["source_url"], "rationale": "r"}
                for c in payload["conflicts"]
            ]
            from services.inference.models import InferenceResult
            return InferenceResult(agent_name="resolution_agent", model="m", provider="fake",
                                   content="{}", parsed_data={"decisions": decisions})

    monkeypatch.setattr(conflict_agent_module, "build_default_gateway", lambda: _CountingGateway())

    state = AgentState(user_query="q", retrieved_programs=[
        _indecisive_candidate("cs", "https://a.test", 120),
        _indecisive_candidate("cs", "https://b.test", 150),
        _indecisive_candidate("ee", "https://c.test", 80),
        _indecisive_candidate("ee", "https://d.test", 95),
    ])

    output = conflict_agent(state)

    assert len(calls) == 1                                  # MỘT call batch cho 2 conflict
    resolved_via_llm = [o for o in output.resolution_outcomes
                        if o.used_llm_tiebreaker and o.status == "resolved"]
    assert len(resolved_via_llm) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/agents/test_conflict_agent.py::test_conflict_agent_batches_indecisive_into_single_llm_call -v`
Expected: FAIL — `conflict_agent_module` chưa có `batch_interpret_conflict_tiebreak`.

- [ ] **Step 3: Write minimal implementation**

`agents/conflict_agent.py` — đổi import (bỏ `interpret_conflict_tiebreak`, thêm batch):

```python
from services.conflict.resolution_inference_service import batch_interpret_conflict_tiebreak
```

Thay nguyên hàm `conflict_agent` (giữ `_mark_uncertain`, `_mark_uncertain_cutoff` không đổi):

```python
def conflict_agent(state: AgentState):
    quota_records = detect_quota_conflicts(state.retrieved_programs)
    cutoff_records = detect_cutoff_conflicts(state.retrieved_programs)
    outcomes = []

    # Gateway (LLM tiebreaker) CHỈ cho quota; cutoff không bao giờ pick-winner bằng LLM (EC-16).
    gateway = build_default_gateway() if quota_records else None

    # Pha A: dựng (record, report) cho mọi quota conflict.
    pairs = []
    for record in quota_records:
        options = package_evidence(record, state.retrieved_programs)
        record.options = options
        report = compare(options)
        pairs.append((record, report))

    # Pha B: chỉ conflict indecisive cần LLM → MỘT call gom cả batch.
    indecisive = [(record, report) for record, report in pairs if not report.is_decisive]
    decisions = (
        batch_interpret_conflict_tiebreak(indecisive, gateway)
        if gateway is not None else {}
    )

    def _lookup(record, report):
        return decisions.get(record.conflict_key, {"confidence": "low"})

    tiebreak = _lookup if gateway is not None else None

    # Pha C: resolve() KHÔNG đổi — nhận callback tra cứu thay vì callback LLM.
    for record, report in pairs:
        outcome = resolve(record, report, gateway=tiebreak)
        outcomes.append(outcome)
        if outcome.status == "unresolved":
            _mark_uncertain(state, record.conflict_key, record.field_name)

    for record in cutoff_records:
        outcome = resolve_cutoff_conflict(record, state.student_profile)
        outcomes.append(outcome)
        if outcome.status == "unresolved":
            _mark_uncertain_cutoff(
                state, record.school_id, record.program_id or record.program_name
            )

    state.conflict_records = quota_records + cutoff_records
    state.resolution_outcomes = outcomes
    state.conflicts = [
        outcome.rationale
        for outcome in outcomes
        if outcome.status == "unresolved" or outcome.used_llm_tiebreaker
    ]
    return state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/agents/test_conflict_agent.py -v`
Expected: PASS — test batch mới, test tiebreaker đã cập nhật, mọi test cutoff (không đổi).

- [ ] **Step 5: Commit**

```bash
git add agents/conflict_agent.py tests/agents/test_conflict_agent.py
git commit -m "feat(conflict): batch quota tiebreak into one LLM call in conflict_agent"
```
