# Plan 01 — 4b: Deterministic all-axes-tie tiebreak

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the LLM conflict tiebreak (which only fires on a perfect
all-axes tie and effectively always returns low confidence) with a deterministic
`tie → unresolved` rule, and remove the code it orphans.

**Architecture:** `compare()` already returns `is_decisive=False` on an all-axes
tie. `resolve()` drops its `gateway` parameter and returns `unresolved` on the
non-decisive branch. `conflict_agent` stops constructing a gateway and batching
LLM tiebreaks. The now-dead `resolution_inference_service` module, the
`resolution_agent` registry entry, and the `used_llm_tiebreaker` field are
removed.

**Tech Stack:** Python, Pydantic v2, pytest.

---

## Why this is safe (read first)

The LLM tiebreak runs only when `first_score == second_score` across every axis
(`comparison_agent.py:26-31`). Its prompt says to return `"high"` confidence
**only when one source is clearly more trustworthy** — impossible under a tie —
so on a genuine tie it returns low → `_unresolved` anyway, at the cost of an LLM
call. Going straight to `unresolved` preserves the effective outcome and never
hides a real disagreement.

Grep verification already done: `batch_interpret_conflict_tiebreak` is called
only by `conflict_agent`; `interpret_conflict_tiebreak` (single) is used only by
its own test; `used_llm_tiebreaker` and `decision_axes=["llm_tiebreaker"]` have
no readers outside the conflict module and its tests.

---

### Task 1: Make `resolve()` deterministic and simplify `conflict_agent`

These two files are coupled (the agent calls `resolve(..., gateway=...)`), so
they change together in one commit to keep the suite green.

**Files:**
- Modify: `services/conflict/resolution_agent.py`
- Modify: `agents/conflict_agent.py`
- Test: `tests/services/conflict/test_resolution_agent.py` (rewrite)
- Test: `tests/agents/test_conflict_agent.py` (edit)

- [ ] **Step 1: Rewrite `tests/services/conflict/test_resolution_agent.py` to the new contract**

```python
from services.conflict.comparison_agent import compare
from services.conflict.models import ConflictRecord, EvidenceOption
from services.conflict.resolution_agent import resolve


def option(value, trust=2, source="mock://a"):
    return EvidenceOption(
        evidence_id=f"{source}|quota",
        source_url=source,
        trust_level=trust,
        confidence_score=0.9,
        value=value,
    )


def record(options):
    return ConflictRecord(
        conflict_key="vnu_uet:2026:cntt:thpt_score",
        field_name="quota",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
        admission_method="thpt_score",
        options=options,
    )


def test_decisive_report_resolves():
    options = [option(120, trust=2), option(150, trust=3, source="mock://b")]

    outcome = resolve(record(options), compare(options))

    assert outcome.status == "resolved"
    assert outcome.resolved_value == 150
    assert outcome.chosen_evidence.source_url == "mock://b"


def test_all_axes_tie_resolves_unresolved():
    # Same trust + confidence, no fetched_at on either, distinct values ->
    # corroboration ties too -> compare() is NOT decisive.
    options = [option(120, trust=2), option(150, trust=2, source="mock://b")]
    report = compare(options)
    assert report.is_decisive is False

    outcome = resolve(record(options), report)

    assert outcome.status == "unresolved"
    assert outcome.resolved_value is None
    assert outcome.uncertainty_reason
```

- [ ] **Step 2: Run the resolution-agent test to verify it fails**

Run: `.venv/bin/python -m pytest tests/services/conflict/test_resolution_agent.py -q`
Expected: FAIL — `resolve()` still requires/accepts a `gateway` arg and the old
test names are gone; `test_all_axes_tie_resolves_unresolved` may pass but
`test_decisive_report_resolves` calls `resolve(record, report)` with the current
2-arg-plus-optional signature (passes) — the real failure surfaces after Step 3
edits. Primary intent: lock the new contract before editing impl.

- [ ] **Step 3: Rewrite the resolution path in `services/conflict/resolution_agent.py`**

Replace the top imports and the `_unresolved` / `_find_option` / `resolve`
block (lines 1-80) with:

```python
from typing import Optional

from services.conflict.models import ComparisonReport, ConflictRecord, EvidenceOption, ResolutionOutcome
from services.cutoff.assessment import classify_margin
from services.profile.admission_methods import THANG_30_METHODS


def _unresolved(record: ConflictRecord, reason: str) -> ResolutionOutcome:
    return ResolutionOutcome(
        conflict_key=record.conflict_key,
        field_name=record.field_name,
        school_id=record.school_id,
        school_name=record.school_name,
        program_name=record.program_name,
        status="unresolved",
        rationale=reason,
        uncertainty_reason=reason,
    )


def resolve(record: ConflictRecord, report: ComparisonReport) -> ResolutionOutcome:
    """Pure-deterministic resolution. A decisive comparison resolves to its
    top-ranked option; an all-axes tie is left unresolved (the caller marks the
    field uncertain and the advisory surfaces every value). No LLM call."""
    if report.is_decisive and report.ranked_options:
        chosen = report.ranked_options[0]
        return ResolutionOutcome(
            conflict_key=record.conflict_key,
            field_name=record.field_name,
            school_id=record.school_id,
            school_name=record.school_name,
            program_name=record.program_name,
            status="resolved",
            resolved_value=chosen.value,
            chosen_evidence=chosen,
            rejected_evidence=report.ranked_options[1:],
            rationale="Resolved by deterministic comparison.",
            decision_axes=report.decision_axes,
        )
    return _unresolved(record, "Comparison was not decisive.")
```

Leave `resolve_cutoff_conflict`, `_fmt_value`, and the `EvidenceOption` import
in place. Note `EvidenceOption` is still imported (used by `resolve_cutoff_conflict`'s
type hints indirectly) — keep it. The `Callable`/`GatewayFunc` type and
`_find_option` are deleted.

> NOTE: `resolve_cutoff_conflict` builds `_unresolved(record, reason)` then sets
> `outcome.rejected_evidence = options` (current line 122-124). That still works
> — `_unresolved` no longer takes a `used_llm` kwarg, and `resolve_cutoff_conflict`
> never passed one. Verify no call site passes `used_llm=`.

- [ ] **Step 4: Simplify `agents/conflict_agent.py`**

Replace the imports (lines 1-7) — drop the gateway + batch import:

```python
from services.conflict.comparison_agent import compare
from services.conflict.detection import detect_cutoff_conflicts, detect_quota_conflicts
from services.conflict.evidence_agent import package_evidence
from services.conflict.resolution_agent import resolve, resolve_cutoff_conflict
from state import AgentState
```

Replace the body of `conflict_agent` (current lines 36-86) with:

```python
def conflict_agent(state: AgentState):
    quota_records = detect_quota_conflicts(state.retrieved_programs)
    cutoff_records = detect_cutoff_conflicts(state.retrieved_programs)
    outcomes = []

    # Quota conflicts: build evidence, compare, resolve deterministically.
    # An all-axes tie resolves to `unresolved` (no LLM tiebreak).
    for record in quota_records:
        options = package_evidence(record, state.retrieved_programs)
        record.options = options
        report = compare(options)
        outcome = resolve(record, report)
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
        outcome.rationale for outcome in outcomes if outcome.status == "unresolved"
    ]
    return state
```

Keep `_mark_uncertain` and `_mark_uncertain_cutoff` unchanged.

> The `state.conflicts` list previously also included outcomes where
> `used_llm_tiebreaker` was true. With the LLM path gone, the only conflict
> rationales worth surfacing are the unresolved ones, so the filter simplifies to
> `status == "unresolved"`.

- [ ] **Step 5: Update `tests/agents/test_conflict_agent.py`**

Delete these two tests entirely (they exercise the removed LLM path):
`test_conflict_agent_resolves_via_llm_tiebreaker` and
`test_conflict_agent_batches_indecisive_into_single_llm_call`. Delete the now-unused
`_indecisive_candidate` helper and the `import json` / `import agents.conflict_agent as conflict_agent_module`
lines **only if** no remaining test references them (the cutoff tests below still
monkeypatch `build_default_gateway`, so adjust those next).

Replace `test_conflict_agent_marks_unresolved_candidates_uncertain` (lines
152-174) with a no-monkeypatch version (no gateway is ever built now):

```python
def test_conflict_agent_tie_resolves_unresolved_and_marks_uncertain():
    state = AgentState(
        user_query="Tu van",
        retrieved_programs=[
            candidate("mock://a", 120, 2),
            candidate("mock://b", 150, 2),
        ],
    )

    output = conflict_agent(state)

    assert output.resolution_outcomes[0].status == "unresolved"
    assert output.conflicts
    assert any(
        "quota" in cand.data_uncertain_fields for cand in output.retrieved_programs
    )
```

In the three cutoff tests (`test_cutoff_decision_changing_...`,
`test_cutoff_same_label_...`, `test_cutoff_without_profile_score_...`), remove the
`monkeypatch.setattr(conflict_agent_module, "build_default_gateway", ...)` lines
and the `monkeypatch` parameter — `conflict_agent` no longer imports or builds a
gateway, so `monkeypatch.setattr` on the missing attribute would now raise. Keep
the `used_llm_tiebreaker is False` assertion in `test_cutoff_decision_changing_...`
for now (the field still exists until Task 3).

After removing the gateway monkeypatches, the `import json` and
`import agents.conflict_agent as conflict_agent_module` imports are unused — delete
them.

- [ ] **Step 6: Run the conflict suite to verify it passes**

Run: `.venv/bin/python -m pytest tests/agents/test_conflict_agent.py tests/services/conflict/test_resolution_agent.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/conflict/resolution_agent.py agents/conflict_agent.py \
  tests/services/conflict/test_resolution_agent.py tests/agents/test_conflict_agent.py
git commit -m "feat(conflict): deterministic all-axes-tie tiebreak (tie -> unresolved, no LLM)"
```

---

### Task 2: Delete the dead LLM-tiebreak module and registry entry

**Files:**
- Delete: `services/conflict/resolution_inference_service.py`
- Delete: `tests/services/conflict/test_resolution_inference_service.py`
- Modify: `services/inference/factory.py:23-29`

- [ ] **Step 1: Confirm the module is dead**

Run: `grep -rn "resolution_inference_service\|interpret_conflict_tiebreak\|batch_interpret_conflict_tiebreak" --include=*.py services/ agents/ web/ tests/`
Expected: matches only inside `resolution_inference_service.py` itself and its
test file (both about to be deleted). If any other module matches, stop and
reconcile.

- [ ] **Step 2: Delete the module and its test**

```bash
git rm services/conflict/resolution_inference_service.py \
  tests/services/conflict/test_resolution_inference_service.py
```

- [ ] **Step 3: Remove the `resolution_agent` registry entry in `services/inference/factory.py`**

Delete these lines (the agent name is only referenced by the deleted module):

```python
            "resolution_agent": {
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash",
                "max_tokens": 256,
            },
```

- [ ] **Step 4: Run the full conflict suite + a factory import smoke check**

Run: `.venv/bin/python -m pytest tests/services/conflict tests/agents/test_conflict_agent.py tests/services/inference -q`
Expected: PASS, no collection error from the removed module.

- [ ] **Step 5: Commit**

```bash
git add services/inference/factory.py
git commit -m "refactor(conflict): drop dead LLM-tiebreak module + resolution_agent registry entry"
```

---

### Task 3: Remove the `used_llm_tiebreaker` field

Now permanently `False` everywhere; remove it and its lone reader.

**Files:**
- Modify: `services/conflict/models.py:47`
- Modify: `agents/conflict_agent.py` (the `state.conflicts` filter is already
  simplified in Task 1 — verify no `used_llm_tiebreaker` reference remains)
- Modify: `tests/agents/test_conflict_agent.py` (remove the lone assertion)

- [ ] **Step 1: Remove the assertion in the cutoff test**

In `tests/agents/test_conflict_agent.py`, in
`test_cutoff_decision_changing_is_unresolved_marks_uncertain`, delete the line:

```python
    assert outcome.used_llm_tiebreaker is False
```

- [ ] **Step 2: Run the test to verify it still passes (field still present)**

Run: `.venv/bin/python -m pytest tests/agents/test_conflict_agent.py -q`
Expected: PASS.

- [ ] **Step 3: Remove the field from `services/conflict/models.py`**

Delete the last line of `ResolutionOutcome`:

```python
    used_llm_tiebreaker: bool = False
```

- [ ] **Step 4: Verify no references remain**

Run: `grep -rn "used_llm_tiebreaker" --include=*.py .`
Expected: **no matches**.

- [ ] **Step 5: Run the full conflict + agents suite**

Run: `.venv/bin/python -m pytest tests/services/conflict tests/agents -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/conflict/models.py tests/agents/test_conflict_agent.py
git commit -m "refactor(conflict): drop now-unused used_llm_tiebreaker field"
```

---

## Done-check for Plan 01

Run the full suite:

Run: `.venv/bin/python -m pytest -q`
Expected: PASS (against `admission_test`; Docker DB up for integration/e2e).

Acceptance (spec 4b): tied conflicts resolve to `unresolved` deterministically
and reproducibly with **zero** LLM calls; cutoff path unchanged; suite green.
