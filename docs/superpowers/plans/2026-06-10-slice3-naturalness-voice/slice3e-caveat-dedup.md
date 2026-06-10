# Slice 3e — De-duplicate Conflict Caveats + Section Bridges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When ≥2 recommended programs carry a data-conflict note, emit a single
consolidated "đối chiếu thông báo chính thức" caveat near the top and shorten each
per-program note to just its differing values. Add a one-line bridge before the
"Không đủ điều kiện xét tuyển" section.

**Architecture:** `_data_note` gains a `concise` flag that drops the repeated
"kiểm tra thông báo chính thức" boilerplate. `build_explanation` counts how many
renderable candidates have a note; when ≥2 it appends one consolidated caveat
after the intro and renders each per-program note in concise form. With 0–1
conflicts, behavior is byte-for-byte unchanged.

**Tech Stack:** Python, pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-slice3-naturalness-voice-design.md` §3e

**Depends on:** slice 3a (the per-program note tails already read "bạn nên kiểm
tra…").

---

### Task 1: Add a `concise` mode to `_data_note`

**Files:**
- Modify: `services/explanation_service.py` (`_data_note`, l.207–234)
- Test: `tests/agents/test_explanation_agent.py`

- [ ] **Step 1: Write the failing unit test**

Append to `tests/agents/test_explanation_agent.py`:

```python
def test_data_note_concise_drops_official_check_boilerplate():
    from services.explanation_service import _data_note
    from agents.models import CandidateProgram

    candidate = CandidateProgram(
        candidate_id="hust:2026:cs:thpt_score", school_id="hust", school_name="HUST",
        admission_year=2026, program_id="cs", program_name="KHMT",
        admission_method="thpt_score", data_uncertain_fields=["quota"],
    )
    full = _data_note(candidate, {})
    concise = _data_note(candidate, {}, concise=True)
    assert "kiểm tra trực tiếp với trường" in full
    assert "kiểm tra trực tiếp với trường" not in concise
    assert concise.startswith("**Lưu ý dữ liệu:**")
```

- [ ] **Step 2: Run to confirm it fails**

Run: `.venv/bin/python -m pytest tests/agents/test_explanation_agent.py -k "concise" -q`
Expected: FAIL — `_data_note` has no `concise` parameter.

- [ ] **Step 3: Add the `concise` flag**

Replace the body of `_data_note` (l.207–234) with:

```python
def _data_note(candidate: CandidateProgram, outcome_by_key: Dict[str, ResolutionOutcome],
               concise: bool = False) -> Optional[str]:
    """Khối '**Lưu ý dữ liệu:**' theo từng chương trình (AC6).

    concise=True bỏ câu nhắc 'kiểm tra thông báo chính thức' (đã gộp lên đầu khi
    ≥2 chương trình mâu thuẫn — 3e)."""
    outcome = outcome_by_key.get(_candidate_conflict_key(candidate))
    if outcome is None and not candidate.data_uncertain_fields:
        return None

    if outcome is not None and outcome.status == "resolved" and outcome.chosen_evidence:
        field = _field_label(outcome.field_name)
        chosen = outcome.chosen_evidence
        all_options = [chosen] + list(outcome.rejected_evidence)
        values = " và ".join(
            f"{_fmt_num(o.value)} ({label_for_source(o.source_url)})" for o in all_options
        )
        note = (
            f"**Lưu ý dữ liệu:** Các nguồn ghi khác nhau về {field}: {values}. "
            f"Hệ thống tham chiếu giá trị {_fmt_num(outcome.resolved_value)} từ "
            f"{label_for_source(chosen.source_url)}"
        )
        if concise:
            return note + "."
        return note + (
            ", nhưng bạn nên kiểm tra thông báo tuyển sinh chính thức mới nhất của "
            "trường trước khi đăng ký."
        )

    if outcome is not None:
        field = _field_label(outcome.field_name)
    else:
        field = ", ".join(_field_label(f) for f in candidate.data_uncertain_fields)
    base = f"**Lưu ý dữ liệu:** Thông tin về {field} đang mâu thuẫn giữa các nguồn."
    if concise:
        return base
    return base + " Bạn nên kiểm tra trực tiếp với trường trước khi đăng ký."
```

- [ ] **Step 4: Run to confirm it passes**

Run: `.venv/bin/python -m pytest tests/agents/test_explanation_agent.py -k "concise" -q`
Expected: PASS. (The existing single-conflict tests still pass — default
`concise=False` reproduces the old text.)

- [ ] **Step 5: Commit**

```bash
git add services/explanation_service.py tests/agents/test_explanation_agent.py
git commit -m "feat(advisory): add concise mode to per-program data note"
```

---

### Task 2: Consolidate the caveat when ≥2 programs conflict

**Files:**
- Modify: `services/explanation_service.py` (`build_explanation`, the renderable block)
- Test: `tests/agents/test_explanation_agent.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/agents/test_explanation_agent.py`:

```python
def _resolved_outcome(conflict_key, value):
    chosen = EvidenceOption(evidence_id=f"mock://{conflict_key}|quota",
                            source_url=f"mock://{conflict_key}", trust_level=3, value=value)
    return ResolutionOutcome(
        conflict_key=conflict_key, field_name="quota", school_id="x", school_name="X",
        program_name="P", status="resolved", resolved_value=value,
        chosen_evidence=chosen, rationale="r", decision_axes=["trust_level"],
    )


def test_multiple_conflicts_consolidate_caveat_once():
    state = AgentState(user_query="Tu van", admission_year=2026)
    state.student_profile = StudentProfile(total_score=27.0, subject_combination="A00")
    state.retrieved_programs = [
        CandidateProgram(candidate_id="hust:2026:cs:thpt_score", school_id="hust",
                         school_name="HUST", admission_year=2026, program_id="cs",
                         program_name="KHMT", admission_method="thpt_score"),
        CandidateProgram(candidate_id="vnu_uet:2026:cntt:thpt_score", school_id="vnu_uet",
                         school_name="UET", admission_year=2026, program_id="cntt",
                         program_name="CNTT", admission_method="thpt_score"),
    ]
    state.ranked_recommendations = [
        RankedRecommendation(candidate_id="hust:2026:cs:thpt_score", band="match", score=0.7, summary="f"),
        RankedRecommendation(candidate_id="vnu_uet:2026:cntt:thpt_score", band="match", score=0.6, summary="f"),
    ]
    state.resolution_outcomes = [
        _resolved_outcome("hust:2026:cs:thpt_score", 100),
        _resolved_outcome("vnu_uet:2026:cntt:thpt_score", 150),
    ]

    answer = explanation_agent(state).final_answer

    # consolidated caveat appears exactly once
    assert answer.count("đối chiếu thông báo tuyển sinh chính thức") == 1
    # per-program boilerplate is dropped (concise notes)
    assert "nhưng bạn nên kiểm tra thông báo" not in answer
    # but per-program specifics survive
    assert "100" in answer and "150" in answer
```

- [ ] **Step 2: Run to confirm it fails**

Run: `.venv/bin/python -m pytest tests/agents/test_explanation_agent.py -k "consolidate" -q`
Expected: FAIL — there is no consolidated caveat; each program still carries the
boilerplate.

- [ ] **Step 3: Add the consolidated-caveat constant**

Add near the other module constants in `services/explanation_service.py`:

```python
_CONSOLIDATED_CONFLICT_CAVEAT = (
    "**Lưu ý dữ liệu:** Một số chương trình dưới đây có dữ liệu chưa thống nhất giữa "
    "các nguồn; bạn nên đối chiếu thông báo tuyển sinh chính thức mới nhất của trường "
    "trước khi đăng ký."
)
```

- [ ] **Step 4: Count conflicts and consolidate in `build_explanation`**

In the `if renderable:` block, right after the intro paragraph append
(`lines.append(_intro_paragraph(...))`) and the historical-cutoff caveat block,
**before** the `for idx, (recommendation, candidate) in enumerate(...)` loop,
insert:

```python
        conflicted = [c for _rec, c in renderable if _data_note(c, outcome_by_key) is not None]
        consolidate = len(conflicted) >= 2
        if consolidate:
            lines.append("")
            lines.append(_CONSOLIDATED_CONFLICT_CAVEAT)
```

Then in the loop, change the per-program note call. Replace:

```python
            note = _data_note(candidate, outcome_by_key)
```

with:

```python
            note = _data_note(candidate, outcome_by_key, concise=consolidate)
```

- [ ] **Step 5: Run to confirm it passes**

Run: `.venv/bin/python -m pytest tests/agents/test_explanation_agent.py -q`
Expected: PASS (consolidation test passes; single-conflict tests unchanged
because `consolidate` is False with one note).

- [ ] **Step 6: Commit**

```bash
git add services/explanation_service.py tests/agents/test_explanation_agent.py
git commit -m "feat(advisory): consolidate conflict caveat once when ≥2 programs conflict"
```

---

### Task 3: Bridge before the "Không đủ điều kiện" section

**Files:**
- Modify: `services/explanation_service.py` (the `ne_lines` block, l.340–345)
- Test: `tests/agents/test_explanation_agent.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/agents/test_explanation_agent.py`:

```python
def test_not_eligible_section_has_bridge_lead_in():
    state = AgentState(user_query="Tu van", admission_year=2026)
    state.retrieved_programs = [
        CandidateProgram(candidate_id="uet:ne", school_id="vnu_uet", school_name="UET",
                         admission_year=2026, program_id="cs", program_name="KHMT",
                         admission_method="thpt_score", subject_combinations=["A00"]),
    ]
    state.eligibility_checks = [
        EligibilityCheck(candidate_id="uet:ne", eligible=False,
                         risks=["Chương trình không nhận tổ hợp D01."]),
    ]
    state.ranked_recommendations = []
    state.policy_decision = PolicyDecision(policy_flags=["no_eligible_recommendations"])

    answer = explanation_agent(state).final_answer
    bridge = "Một vài chương trình bạn quan tâm chưa đáp ứng điều kiện xét tuyển:"
    assert bridge in answer
    assert answer.index(bridge) < answer.index("**Không đủ điều kiện xét tuyển**")
```

- [ ] **Step 2: Run to confirm it fails**

Run: `.venv/bin/python -m pytest tests/agents/test_explanation_agent.py -k "bridge" -q`
Expected: FAIL — no bridge line precedes the header.

- [ ] **Step 3: Add the bridge before the header**

In the `ne_lines` block, replace:

```python
    if ne_lines:
        lines.append("")
        lines.append("**Không đủ điều kiện xét tuyển**")
        lines.append("")
        lines.extend(ne_lines)
```

with:

```python
    if ne_lines:
        lines.append("")
        lines.append("Một vài chương trình bạn quan tâm chưa đáp ứng điều kiện xét tuyển:")
        lines.append("")
        lines.append("**Không đủ điều kiện xét tuyển**")
        lines.append("")
        lines.extend(ne_lines)
```

- [ ] **Step 4: Run to confirm it passes**

Run: `.venv/bin/python -m pytest tests/agents/test_explanation_agent.py -q`
Expected: PASS (existing not-eligible tests assert the header and ordering vs
`### 1.`, both still hold).

- [ ] **Step 5: Run the full suite + commit**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

```bash
git add services/explanation_service.py tests/agents/test_explanation_agent.py
git commit -m "feat(advisory): add bridge lead-in before not-eligible section"
```
