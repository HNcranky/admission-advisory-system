# Cutoff Plan 4 — Conflict mở rộng, explanation & e2e acceptance

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `detect_cutoff_conflicts` + outcome deterministic không LLM (EC-16), explanation render dòng tham chiếu + dual-source + caveat toàn cục EC-18, fix `_data_note` liệt kê đủ giá trị cho quota (EC-17), e2e acceptance 4 kịch bản GWT.

**Architecture:** Cutoff conflict nhóm theo `(school, program, cutoff_year, method)` với options theo `source_url` (dedupe — nhiều candidate row chia sẻ cùng history). `ConflictRecord.admission_year` mang **cutoff_year**. Outcome: decision-changing (dùng `classify_margin` của assessment) → `unresolved` → marker riêng `_mark_uncertain_cutoff` (match theo school+program, vì conflict_key cutoff chứa cutoff_year nên không khớp key candidate). Không decision-changing → `resolved` theo trust, rationale luôn nêu đủ giá trị.

**Tech Stack:** pytest, pattern fixture của `tests/agents/test_conflict_agent.py` / `test_explanation_agent.py` / `tests/e2e/test_advisory_flow.py`.

**Phụ thuộc:** Plan 3 (`classify_margin`, reasoning cautions). Runtime production cần Plan 2.

---

### Task 1: `detect_cutoff_conflicts`

**Files:**
- Modify: `services/conflict/detection.py`
- Test: `tests/services/conflict/test_detection.py` (append)

- [ ] **Step 1: Viết test fail** — append (file đã import `CandidateProgram`; thêm `from agents.models import CutoffEntry` và `from services.conflict.detection import detect_cutoff_conflicts` ở đầu file nếu thiếu):

```python
def _cutoff_candidate(candidate_id="hust:2026:computer_science:thpt_score", history=()):
    return CandidateProgram(
        candidate_id=candidate_id, school_id="hust", school_name="HUST",
        admission_year=2026, program_id="computer_science",
        program_name="Khoa hoc May tinh", admission_method="thpt_score",
        cutoff_history=list(history),
    )


def _ce(year, score, source, trust=5):
    return CutoffEntry(cutoff_year=year, admission_method="thpt_score",
                       cutoff_score=score, score_scale=30.0,
                       source_url=source, trust_level=trust)


def test_detect_cutoff_conflicts_two_sources_distinct_values():
    candidate = _cutoff_candidate(history=[
        _ce(2025, 26.2, "https://truong/dc"), _ce(2025, 26.8, "https://dhqg/dc", trust=4),
    ])
    records = detect_cutoff_conflicts([candidate])

    assert len(records) == 1
    record = records[0]
    assert record.field_name == "cutoff_score"
    assert record.admission_year == 2025                  # mang CUTOFF_YEAR
    assert record.conflict_key.endswith(":cutoff")
    assert {o.value for o in record.options} == {26.2, 26.8}


def test_detect_cutoff_conflicts_dedupes_shared_history_across_rows():
    """Hai candidate row (2 phương thức) chia sẻ cùng history (attach theo school+program)
    → options KHÔNG được nhân đôi."""
    history = [_ce(2025, 26.2, "https://a"), _ce(2025, 26.8, "https://b")]
    rows = [
        _cutoff_candidate(history=history),
        _cutoff_candidate(candidate_id="hust:2026:computer_science:talent", history=history),
    ]
    records = detect_cutoff_conflicts(rows)
    assert len(records) == 1 and len(records[0].options) == 2


def test_detect_cutoff_conflicts_ignores_same_value_or_single_source():
    same = _cutoff_candidate(history=[_ce(2025, 26.2, "https://a"), _ce(2025, 26.2, "https://b")])
    single = _cutoff_candidate(history=[_ce(2025, 26.2, "https://a")])
    assert detect_cutoff_conflicts([same]) == []
    assert detect_cutoff_conflicts([single]) == []


def test_detect_cutoff_conflicts_groups_per_year():
    candidate = _cutoff_candidate(history=[
        _ce(2025, 26.2, "https://a"), _ce(2025, 26.8, "https://b"),
        _ce(2024, 25.0, "https://a"),                     # năm khác, 1 nguồn → không conflict
    ])
    records = detect_cutoff_conflicts([candidate])
    assert len(records) == 1 and records[0].admission_year == 2025
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/services/conflict/test_detection.py -q`
Expected: FAIL — `ImportError: cannot import name 'detect_cutoff_conflicts'`

- [ ] **Step 3: Implement** — append vào `services/conflict/detection.py` (import sẵn đủ):

```python
def detect_cutoff_conflicts(candidates: List[CandidateProgram]) -> List[ConflictRecord]:
    """Conflict điểm chuẩn giữa các nguồn (EC-16).

    Group theo (school_id, program, cutoff_year, method); options theo source_url
    (dedupe — nhiều candidate row có thể chia sẻ cùng cutoff_history vì attach
    theo (school, program)). LƯU Ý: ConflictRecord.admission_year mang CUTOFF_YEAR
    (năm của điểm chuẩn lịch sử), khác quota conflicts (năm đề án).
    """
    per_source: Dict[Tuple[str, str, int, str], Dict[str, Any]] = {}
    sample: Dict[Tuple[str, str, int, str], CandidateProgram] = {}
    for candidate in candidates:
        program_key = candidate.program_id or candidate.program_name
        for entry in candidate.cutoff_history:
            key = (candidate.school_id, program_key, entry.cutoff_year, entry.admission_method)
            per_source.setdefault(key, {}).setdefault(entry.source_url, entry)
            sample.setdefault(key, candidate)

    records: List[ConflictRecord] = []
    for key, by_source in per_source.items():
        entries = list(by_source.values())
        if len({e.cutoff_score for e in entries}) < 2:
            continue
        school_id, program_key, cutoff_year, method = key
        candidate = sample[key]
        records.append(
            ConflictRecord(
                conflict_key=f"{school_id}:{cutoff_year}:{program_key}:{method}:cutoff",
                field_name="cutoff_score",
                school_id=school_id,
                school_name=candidate.school_name,
                admission_year=cutoff_year,
                program_id=candidate.program_id,
                program_name=candidate.program_name,
                admission_method=method,
                options=[
                    EvidenceOption(
                        evidence_id=f"{e.source_url}|cutoff_score",
                        source_url=e.source_url,
                        trust_level=e.trust_level,
                        value=e.cutoff_score,
                    )
                    for e in entries
                ],
            )
        )
    return records
```

- [ ] **Step 4: Chạy test**

Run: `python -m pytest tests/services/conflict/test_detection.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/conflict/detection.py tests/services/conflict/test_detection.py
git commit -m "feat: detect cutoff conflicts across sources per (program, year, method)"
```

---

### Task 2: `resolve_cutoff_conflict` + nhánh trong `conflict_agent`

**Files:**
- Modify: `services/conflict/resolution_agent.py`
- Modify: `agents/conflict_agent.py`
- Test: `tests/agents/test_conflict_agent.py` (append)

- [ ] **Step 1: Viết test fail** — append vào `tests/agents/test_conflict_agent.py` (thêm import: `from agents.models import CutoffEntry, StudentProfile`):

```python
def _cutoff_state(total_score, values_by_source, trusts=(4, 5)):
    history = [
        CutoffEntry(cutoff_year=2025, admission_method="thpt_score", cutoff_score=v,
                    score_scale=30.0, source_url=u, trust_level=t)
        for (u, v), t in zip(values_by_source.items(), trusts)
    ]
    return AgentState(
        user_query="Tu van",
        student_profile=StudentProfile(total_score=total_score, admission_method="thpt_score"),
        retrieved_programs=[
            CandidateProgram(
                candidate_id="hust:2026:computer_science:thpt_score", school_id="hust",
                school_name="HUST", admission_year=2026, program_id="computer_science",
                program_name="Khoa hoc May tinh", admission_method="thpt_score",
                cutoff_history=history,
            )
        ],
    )


def test_cutoff_decision_changing_is_unresolved_marks_uncertain_no_llm(monkeypatch):
    def explode():
        raise AssertionError("LLM gateway must NEVER be built for cutoff-only conflicts")

    monkeypatch.setattr(conflict_agent_module, "build_default_gateway", explode)

    # 26.5 nằm giữa 26.2 (above) và 26.8 (below) → decision-changing (EC-16).
    state = _cutoff_state(26.5, {"https://truong/dc": 26.2, "https://dhqg/dc": 26.8})
    output = conflict_agent(state)

    outcome = output.resolution_outcomes[0]
    assert outcome.field_name == "cutoff_score"
    assert outcome.status == "unresolved"
    assert outcome.used_llm_tiebreaker is False
    assert "26.2" in outcome.rationale and "26.8" in outcome.rationale
    assert "cutoff_score" in output.retrieved_programs[0].data_uncertain_fields
    assert output.conflicts                                # nuôi policy flag retrieval_conflicts_detected


def test_cutoff_same_label_resolves_by_trust_with_full_rationale(monkeypatch):
    monkeypatch.setattr(
        conflict_agent_module, "build_default_gateway",
        lambda: (_ for _ in ()).throw(AssertionError("no gateway for cutoff")),
    )
    # 28.0 trên cả 25.0 lẫn 25.2 → cùng nhãn above → resolved theo trust cao nhất (25.2, trust 5).
    state = _cutoff_state(28.0, {"https://truong/dc": 25.0, "https://dhqg/dc": 25.2})
    output = conflict_agent(state)

    outcome = output.resolution_outcomes[0]
    assert outcome.status == "resolved"
    assert outcome.resolved_value == 25.2
    assert "25" in outcome.rationale and len(outcome.rejected_evidence) == 1
    assert "cutoff_score" not in output.retrieved_programs[0].data_uncertain_fields


def test_cutoff_without_profile_score_resolves_by_trust(monkeypatch):
    monkeypatch.setattr(
        conflict_agent_module, "build_default_gateway",
        lambda: (_ for _ in ()).throw(AssertionError("no gateway for cutoff")),
    )
    state = _cutoff_state(26.5, {"https://truong/dc": 26.2, "https://dhqg/dc": 26.8})
    state.student_profile = StudentProfile()              # thiếu điểm → không phân loại được
    output = conflict_agent(state)

    assert output.resolution_outcomes[0].status == "resolved"
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/agents/test_conflict_agent.py -q`
Expected: 3 test mới FAIL (cutoff records chưa được detect/resolve).

- [ ] **Step 3: Implement `resolve_cutoff_conflict`** — trong `services/conflict/resolution_agent.py`, thêm import đầu file:

```python
from services.cutoff.assessment import classify_margin
from services.profile.admission_methods import THANG_30_METHODS
```

và hàm mới cuối file:

```python
def _fmt_value(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def resolve_cutoff_conflict(record: ConflictRecord, profile) -> ResolutionOutcome:
    """EC-16: cutoff KHÔNG BAO GIỜ qua LLM pick-winner.

    Decision-changing (các giá trị cho nhãn khác nhau với điểm hồ sơ) → unresolved
    (caller mark uncertain + explanation hiển thị đủ giá trị). Ngược lại (cùng nhãn,
    hoặc thiếu điểm/phương thức để phân loại) → resolved theo nguồn trust cao nhất,
    rationale luôn nêu đủ các giá trị.
    """
    options = sorted(
        record.options,
        key=lambda o: (
            -(o.trust_level if o.trust_level is not None else -1),
            -(o.value if isinstance(o.value, (int, float)) else 0),
        ),
    )
    values_text = " / ".join(_fmt_value(o.value) for o in options)

    total_score = getattr(profile, "total_score", None)
    method = getattr(profile, "admission_method", None)
    decision_changing = False
    if total_score is not None and method in THANG_30_METHODS:
        fits = {
            classify_margin(total_score, o.value)
            for o in options
            if isinstance(o.value, (int, float))
        }
        decision_changing = len(fits) > 1

    if decision_changing:
        reason = (
            f"Kết luận thay đổi theo nguồn: các nguồn ghi {values_text} cho điểm chuẩn "
            f"tham chiếu {record.admission_year} của {record.program_name}."
        )
        outcome = _unresolved(record, reason)
        outcome.rejected_evidence = options
        return outcome

    chosen = options[0]
    return ResolutionOutcome(
        conflict_key=record.conflict_key,
        field_name=record.field_name,
        school_id=record.school_id,
        school_name=record.school_name,
        program_name=record.program_name,
        status="resolved",
        resolved_value=chosen.value,
        chosen_evidence=chosen,
        rejected_evidence=options[1:],
        rationale=(
            f"Các nguồn ghi khác nhau ({values_text}); hệ thống tham chiếu giá trị "
            f"{_fmt_value(chosen.value)} từ nguồn tin cậy cao nhất."
        ),
        decision_axes=["trust_level"],
    )
```

- [ ] **Step 4: Implement nhánh trong `agents/conflict_agent.py`** — thay toàn bộ file bằng:

```python
from services import build_default_gateway
from services.conflict.comparison_agent import compare
from services.conflict.detection import detect_cutoff_conflicts, detect_quota_conflicts
from services.conflict.evidence_agent import package_evidence
from services.conflict.resolution_agent import resolve, resolve_cutoff_conflict
from services.conflict.resolution_inference_service import interpret_conflict_tiebreak
from state import AgentState


def _mark_uncertain(state: AgentState, conflict_key: str, field_name: str) -> None:
    for candidate in state.retrieved_programs:
        key = ":".join(
            [
                candidate.school_id,
                str(candidate.admission_year),
                candidate.program_id or candidate.program_name,
                candidate.admission_method or "unknown_method",
            ]
        )
        if key == conflict_key and field_name not in candidate.data_uncertain_fields:
            candidate.data_uncertain_fields.append(field_name)


def _mark_uncertain_cutoff(state: AgentState, school_id: str, program_key: str) -> None:
    """conflict_key của cutoff chứa cutoff_year (≠ admission_year của candidate)
    nên không match key candidate — mark theo (school, program)."""
    for candidate in state.retrieved_programs:
        if candidate.school_id != school_id:
            continue
        if (candidate.program_id or candidate.program_name) != program_key:
            continue
        if "cutoff_score" not in candidate.data_uncertain_fields:
            candidate.data_uncertain_fields.append("cutoff_score")


def conflict_agent(state: AgentState):
    quota_records = detect_quota_conflicts(state.retrieved_programs)
    cutoff_records = detect_cutoff_conflicts(state.retrieved_programs)
    outcomes = []

    # Gateway (LLM tiebreaker) CHỈ cho quota; cutoff không bao giờ pick-winner bằng LLM (EC-16).
    gateway = build_default_gateway() if quota_records else None
    tiebreak = (
        (lambda record, report: interpret_conflict_tiebreak(record, report, gateway))
        if gateway is not None
        else None
    )

    for record in quota_records:
        options = package_evidence(record, state.retrieved_programs)
        record.options = options
        report = compare(options)
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

- [ ] **Step 5: Chạy test**

Run: `python -m pytest tests/agents/test_conflict_agent.py tests/e2e/test_real_conflict_resolution.py -q`
Expected: PASS toàn bộ (test quota cũ giữ nguyên hành vi).

- [ ] **Step 6: Commit**

```bash
git add services/conflict/resolution_agent.py agents/conflict_agent.py tests/agents/test_conflict_agent.py
git commit -m "feat: deterministic cutoff conflict resolution without LLM tiebreaker (EC-16)"
```

---

### Task 3: Explanation — dòng tham chiếu, caveat EC-18, fix EC-17

**Files:**
- Modify: `services/explanation_service.py`
- Test: `tests/agents/test_explanation_agent.py` (append)

- [ ] **Step 1: Viết test fail** — append (thêm import: `from agents.models import CutoffAssessment`):

```python
def _candidate_with_rec(assessment=None, policy=None):
    state = AgentState(user_query="Tu van", admission_year=2026)
    state.student_profile = StudentProfile(
        total_score=26.5, admission_method="thpt_score", subject_combination="A00",
        preferred_majors=["computer_science"],
    )
    state.retrieved_programs = [
        CandidateProgram(
            candidate_id="hust:1", school_id="hust", school_name="HUST",
            admission_year=2026, program_id="computer_science",
            program_name="Khoa hoc May tinh", admission_method="thpt_score",
            evidence=[Evidence(source_url="https://src", school_name="HUST",
                               admission_year=2026, field_name="record")],
        )
    ]
    state.ranked_recommendations = [
        RankedRecommendation(candidate_id="hust:1", band="match", score=0.6,
                             summary="fit", cutoff_assessment=assessment)
    ]
    state.policy_decision = policy
    return state


def test_cutoff_reference_line_renders_all_values():
    assessment = CutoffAssessment(
        score_fit="below", reference_year=2025, margin=-0.3,
        latest_values=[
            {"value": 26.2, "source_url": "mock://uet/program-page", "trust_level": 4},
            {"value": 26.8, "source_url": "mock://vnu/proposal-pdf", "trust_level": 5},
        ],
        conflicted=True, decision_changing=True,
    )
    output = explanation_agent(_candidate_with_rec(assessment))

    answer = output.final_answer
    assert "Điểm chuẩn tham chiếu 2025" in answer
    assert "26.2" in answer and "26.8" in answer           # EC-16: hiển thị CẢ HAI giá trị


def test_global_caveat_renders_with_policy_flag():
    assessment = CutoffAssessment(score_fit="above", reference_year=2025, margin=1.5)
    policy = PolicyDecision(policy_flags=["historical_cutoff_reference"])
    output = explanation_agent(_candidate_with_rec(assessment, policy))

    answer = output.final_answer
    assert "Chưa có điểm chuẩn chính thức cho kỳ tuyển sinh năm 2026" in answer
    assert "dữ liệu năm 2025 làm tham chiếu" in answer


def test_no_global_caveat_without_flag():
    assessment = CutoffAssessment(score_fit="above", reference_year=2025, margin=1.5)
    output = explanation_agent(_candidate_with_rec(assessment, PolicyDecision()))
    assert "Chưa có điểm chuẩn chính thức" not in output.final_answer


def test_ec17_data_note_lists_both_quota_values_with_sources():
    chosen = EvidenceOption(evidence_id="mock://vnu/proposal-pdf|quota",
                            source_url="mock://vnu/proposal-pdf", trust_level=3, value=150)
    rejected = EvidenceOption(evidence_id="mock://uet/program-page|quota",
                              source_url="mock://uet/program-page", trust_level=2, value=120)
    state = _candidate_with_rec()
    state.retrieved_programs[0].candidate_id = "hust:2026:computer_science:thpt_score"
    state.ranked_recommendations[0].candidate_id = "hust:2026:computer_science:thpt_score"
    state.resolution_outcomes = [
        ResolutionOutcome(
            conflict_key="hust:2026:computer_science:thpt_score", field_name="quota",
            school_id="hust", school_name="HUST", program_name="Khoa hoc May tinh",
            status="resolved", resolved_value=150,
            chosen_evidence=chosen, rejected_evidence=[rejected],
            rationale="Resolved by deterministic comparison.", decision_axes=["trust_level"],
        )
    ]
    output = explanation_agent(state)

    answer = output.final_answer
    assert "120" in answer and "150" in answer             # EC-17: đủ CẢ HAI giá trị + nguồn
    assert "tham chiếu giá trị 150" in answer
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/agents/test_explanation_agent.py -q`
Expected: 4 test mới FAIL; test cũ PASS.

- [ ] **Step 3: Implement** — sửa `services/explanation_service.py`:

(a) `_FIELD_LABELS` (dòng 51-55) thêm:

```python
    "cutoff_score": "điểm chuẩn",
```

(b) Thêm helper sau `_program_label` (sau dòng 82):

```python
def _cutoff_reference_line(assessment) -> str:
    """'Điểm chuẩn tham chiếu {year}: v1 (nguồn A) / v2 (nguồn B)' — EC-16 dual display."""
    values = " / ".join(
        f"{_fmt_num(v['value'])} ({label_for_source(v['source_url'])})"
        for v in assessment.latest_values
    )
    return f"Điểm chuẩn tham chiếu {assessment.reference_year}: {values}"
```

(c) Trong `build_explanation`, NGAY SAU dòng `lines.append(_intro_paragraph(...))` (dòng 285) thêm caveat EC-18:

```python
        ref_years = sorted({
            rec.cutoff_assessment.reference_year
            for rec, _candidate in renderable
            if rec.cutoff_assessment is not None
        })
        if ref_years and policy and "historical_cutoff_reference" in policy.policy_flags:
            years_text = ", ".join(str(y) for y in ref_years)
            target = f"năm {admission_year}" if admission_year else "sắp tới"
            lines.append("")
            lines.append(
                f"Chưa có điểm chuẩn chính thức cho kỳ tuyển sinh {target}. "
                f"Đánh giá dưới đây sử dụng dữ liệu năm {years_text} làm tham chiếu "
                "và có thể thay đổi khi trường công bố thông tin mới."
            )
```

(d) Trong vòng render per-program, sửa khối bullets (dòng 292-297) thành:

```python
            bullets = [_translate(r) for r in recommendation.reasons[:3]]
            bullets += [_translate(c) for c in recommendation.cautions[:3]]
            if recommendation.cutoff_assessment is not None and recommendation.cutoff_assessment.latest_values:
                bullets.append(_cutoff_reference_line(recommendation.cutoff_assessment))
            if bullets:
                lines.append("")
                for bullet in bullets:
                    lines.append(f"- {bullet}")
```

(Nhãn score-fit "Sát ngưỡng/Trên mức/Dưới mức/dao động" KHÔNG render thêm ở đây —
chúng đã nằm trong `reasons`/`cautions` từ reasoning (Plan 3), tránh lặp đôi.)

(e) Fix EC-17 — thay nhánh resolved trong `_data_note` (dòng 203-210) bằng:

```python
    if outcome is not None and outcome.status == "resolved" and outcome.chosen_evidence:
        field = _field_label(outcome.field_name)
        chosen = outcome.chosen_evidence
        all_options = [chosen] + list(outcome.rejected_evidence)
        values = " và ".join(
            f"{_fmt_num(o.value)} ({label_for_source(o.source_url)})" for o in all_options
        )
        return (
            f"**Lưu ý dữ liệu:** Các nguồn ghi khác nhau về {field}: {values}. "
            f"Hệ thống tham chiếu giá trị {_fmt_num(outcome.resolved_value)} từ "
            f"{label_for_source(chosen.source_url)}, nhưng em nên kiểm tra thông báo "
            "tuyển sinh chính thức mới nhất của trường trước khi đăng ký."
        )
```

- [ ] **Step 4: Chạy test**

Run: `python -m pytest tests/agents/test_explanation_agent.py tests/services -q`
Expected: PASS toàn bộ (test resolved-note cũ vẫn xanh — fixture cũ không có rejected_evidence nên chỉ liệt kê 1 giá trị).

- [ ] **Step 5: Commit**

```bash
git add services/explanation_service.py tests/agents/test_explanation_agent.py
git commit -m "feat: cutoff reference display, EC-18 caveat, full-values data note (EC-16/17/18)"
```

---

### Task 4: E2E acceptance — 4 kịch bản GWT từ edge-case.md

**Files:**
- Test: `tests/e2e/test_advisory_flow.py` (append)

- [ ] **Step 1: Viết 4 test** — append (thêm import: `from agents.models import CutoffEntry`):

```python
def _cutoff_profile(total_score):
    return StudentProfile(
        total_score=total_score, admission_method="thpt_score", subject_combination="A00",
        preferred_majors=["computer_science"], preferred_schools=["hust"], missing_slots=[],
    )


def _cutoff_candidate(history):
    return CandidateProgram(
        candidate_id="hust:2026:computer_science:thpt_score", school_id="hust",
        school_name="HUST", admission_year=2026, program_id="computer_science",
        program_name="Khoa hoc May tinh", admission_method="thpt_score",
        subject_combinations=["A00", "A01"],
        evidence=[Evidence(source_url="https://example.com/hust-cs", school_name="HUST",
                           admission_year=2026, field_name="record")],
        cutoff_history=history,
    )


def _ch(year, score, source="https://ts.hust.edu.vn/dc", trust=5):
    return CutoffEntry(cutoff_year=year, admission_method="thpt_score", cutoff_score=score,
                       score_scale=30.0, source_url=source, trust_level=trust)


def _run_cutoff_flow(monkeypatch, total_score, history):
    monkeypatch.setattr(
        profile_agent_module, "build_profile_with_gateway",
        lambda user_query, gateway: _cutoff_profile(total_score),
    )
    monkeypatch.setattr(
        retrieval_agent, "fetch_candidates",
        lambda filters, limit=100: [_cutoff_candidate(history)],
    )
    state = AgentState(user_query="Em muon hoc CNTT o HUST", admission_year=2026)
    return graph.invoke(state)


def test_ec14_borderline_score_never_asserted_safe(monkeypatch):
    """EC-14: 26.25 vs cutoff 26.20 (+0.05) → sát ngưỡng, không nhãn an toàn."""
    result = _run_cutoff_flow(monkeypatch, 26.25, [_ch(2025, 26.20)])

    answer = result["final_answer"]
    assert "sát ngưỡng tham chiếu 2025" in answer.lower()
    assert "**Mức phù hợp: Cao / An toàn**" not in answer
    assert "no_admission_assertion_on_reference_cutoff" in result["policy_decision"].blocked_claims


def test_ec15_volatile_cutoffs_warn_and_stay_uncertain(monkeypatch):
    """EC-15: 24.8/26.7/25.9 → cảnh báo biến động, không kết luận."""
    result = _run_cutoff_flow(
        monkeypatch, 26.4, [_ch(2023, 24.8), _ch(2024, 26.7), _ch(2025, 25.9)],
    )

    answer = result["final_answer"]
    assert "dao động 24.8–26.7" in answer
    assert "chưa thể kết luận" in answer
    assert "**Mức phù hợp: Cao / An toàn**" not in answer


def test_ec16_conflicting_cutoffs_show_both_sources_no_single_verdict(monkeypatch):
    """EC-16: 26.2 vs 26.8, điểm 26.5 → hiện CẢ HAI giá trị, nhãn thận trọng, conflict flag."""
    history = [
        _ch(2025, 26.2, source="https://truong.example/dc", trust=4),
        _ch(2025, 26.8, source="https://dhqg.example/dc", trust=5),
    ]
    result = _run_cutoff_flow(monkeypatch, 26.5, history)

    answer = result["final_answer"]
    assert "26.2" in answer and "26.8" in answer
    assert "các nguồn ghi khác nhau về điểm chuẩn" in answer.lower()
    assert "**Mức phù hợp: Cần cân nhắc**" in answer       # nhãn bảo thủ (below → reach)
    assert "retrieval_conflicts_detected" in result["policy_decision"].policy_flags


def test_ec18_reference_year_caveat_always_present_with_cutoff_data(monkeypatch):
    """EC-18: dùng cutoff lịch sử → caveat năm tham chiếu, không khẳng định 2026."""
    result = _run_cutoff_flow(monkeypatch, 28.0, [_ch(2025, 26.5)])

    answer = result["final_answer"]
    assert "Chưa có điểm chuẩn chính thức cho kỳ tuyển sinh năm 2026" in answer
    assert "dữ liệu năm 2025 làm tham chiếu" in answer
    assert "Điểm chuẩn tham chiếu 2025" in answer
    assert "historical_cutoff_reference" in result["policy_decision"].policy_flags
```

Lưu ý: các kịch bản này không có quota conflict → `conflict_agent` không build gateway;
EC-16 conflict đi nhánh deterministic nên KHÔNG cần monkeypatch policy gateway
(policy_agent chỉ gọi LLM khi có conflicts — nếu chạy DB-less không có API key, policy đã
degrade graceful theo pattern hiện có; nếu test EC-16 flake vì gateway, monkeypatch
`policy_agent_module.build_default_gateway` trả fake như `test_advisory_flow_surfaces_uncertainty_for_policy_ambiguity`).

- [ ] **Step 2: Chạy**

Run: `python -m pytest tests/e2e/test_advisory_flow.py -q`
Expected: PASS 4 test mới + 4 test cũ.

- [ ] **Step 3: Chạy toàn suite**

Run: `python -m pytest -q`
Expected: PASS toàn bộ (DB-less: integration tự skip).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_advisory_flow.py
git commit -m "test: e2e acceptance for EC-14/15/16/18 cutoff scenarios"
```
