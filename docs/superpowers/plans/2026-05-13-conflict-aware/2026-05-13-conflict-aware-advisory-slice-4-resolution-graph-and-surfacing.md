# Slice 4 - Resolution Graph and Surfacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Do not create commits for this project unless the user explicitly asks.** Use checkpoint steps instead of `git commit`.

**Goal:** Build the Evidence/Comparison/Resolution layer, wire it into the graph between retrieval and reasoning, and surface `Xác minh dữ liệu` in final answers for mock and synthetic conflict cases.

**Architecture:** Keep detection deterministic from Slice 3. Add source labeling, evidence packaging, comparison, and resolution services. Rewrite `agents/conflict_agent.py` as the conflict-node orchestrator. Extend reasoning to downgrade unresolved quota candidates, and extend explanation to render deterministic Vietnamese verification text.

**Tech Stack:** Python, Pydantic, LangGraph, pytest, existing inference gateway.

---

## File Structure

- Create: `services/conflict/source_labels.py`
- Create: `services/conflict/evidence_agent.py`
- Create: `services/conflict/comparison_agent.py`
- Create: `services/conflict/resolution_agent.py`
- Modify: `services/conflict_resolution_service.py`
- Modify: `agents/conflict_agent.py`
- Modify: `graph.py`
- Modify: `services/reasoning_service.py`
- Modify: `services/explanation_service.py`
- Modify: `agents/explanation_agent.py`
- Create: `tests/services/conflict/test_source_labels.py`
- Create: `tests/services/conflict/test_evidence_agent.py`
- Create: `tests/services/conflict/test_comparison_agent.py`
- Create: `tests/services/conflict/test_resolution_agent.py`
- Create: `tests/agents/test_conflict_agent.py`
- Modify/create: `tests/agents/test_reasoning_agent.py`
- Modify/create: `tests/agents/test_explanation_agent.py`
- Modify/create: `tests/e2e/test_advisory_flow.py`

---

## Task 1: Source Labels

**Files:**
- Create: `services/conflict/source_labels.py`
- Create: `tests/services/conflict/test_source_labels.py`

- [ ] **Step 1: Write failing tests**

Create `tests/services/conflict/test_source_labels.py`:

```python
from services.conflict.source_labels import label_for_source


def test_mock_sources_have_readable_labels():
    assert label_for_source("mock://uet/program-page") == "Nguon mock: UET program page"
    assert label_for_source("mock://vnu/proposal-pdf") == "Nguon mock: VNU proposal PDF"


def test_known_hosts_have_vietnamese_labels():
    assert label_for_source("https://uet.vnu.edu.vn/tuyen-sinh") == "Trang tuyen sinh UET (DHQGHN)"
    assert label_for_source("https://vnu.edu.vn/de-an.pdf") == "De an tuyen sinh DHQGHN"
    assert label_for_source("https://ts.hust.edu.vn/tin-tuc") == "Trang tuyen sinh HUST"


def test_unknown_and_empty_sources_fallback_safely():
    assert label_for_source("https://example.edu.vn/a") == "Nguon: example.edu.vn"
    assert label_for_source("") == "Nguon khong xac dinh"
    assert label_for_source("not-a-url") == "Nguon khong xac dinh"
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
pytest tests/services/conflict/test_source_labels.py -v
```

Expected: FAIL because module is missing.

- [ ] **Step 3: Implement source labels**

Create `services/conflict/source_labels.py`:

```python
from urllib.parse import urlparse

MOCK_LABELS = {
    "mock://uet/program-page": "Nguon mock: UET program page",
    "mock://vnu/proposal-pdf": "Nguon mock: VNU proposal PDF",
    "mock://uet/admission-news": "Nguon mock: UET admission news",
}

HOST_LABELS = {
    "uet.vnu.edu.vn": "Trang tuyen sinh UET (DHQGHN)",
    "vnu.edu.vn": "De an tuyen sinh DHQGHN",
    "ts.hust.edu.vn": "Trang tuyen sinh HUST",
    "hust.edu.vn": "Trang tuyen sinh HUST",
}


def label_for_source(source_url: str) -> str:
    if not source_url:
        return "Nguon khong xac dinh"
    if source_url in MOCK_LABELS:
        return MOCK_LABELS[source_url]

    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "Nguon khong xac dinh"
    hostname = parsed.netloc.lower()
    return HOST_LABELS.get(hostname, f"Nguon: {hostname}")
```

- [ ] **Step 4: Run tests**

Run:

```powershell
pytest tests/services/conflict/test_source_labels.py -v
```

Expected: PASS.

---

## Task 2: Evidence Packaging with Mock Bypass

**Files:**
- Create: `services/conflict/evidence_agent.py`
- Create: `tests/services/conflict/test_evidence_agent.py`

- [ ] **Step 1: Write failing tests**

Create `tests/services/conflict/test_evidence_agent.py`:

```python
from agents.models import CandidateProgram, Evidence
from services.conflict.detection import detect_quota_conflicts
from services.conflict.evidence_agent import package_evidence


def candidate(source_url, quota, trust=2):
    return CandidateProgram(
        candidate_id="vnu_uet:2026:cntt:thpt_score",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
        admission_method="thpt_score",
        quota={"value": quota, "unit": "students"},
        metadata={"mock_conflict": source_url.startswith("mock://")},
        evidence=[
            Evidence(
                source_url=source_url,
                school_name="Dai hoc Cong nghe - DHQGHN",
                admission_year=2026,
                field_name="quota",
                normalized_value={"value": quota, "unit": "students"},
                trust_level=trust,
                confidence_score=0.9,
            )
        ],
    )


def test_package_evidence_uses_candidate_evidence_for_mock_sources(monkeypatch):
    candidates = [
        candidate("mock://uet/program-page", 120, trust=2),
        candidate("mock://vnu/proposal-pdf", 150, trust=3),
    ]
    record = detect_quota_conflicts(candidates)[0]

    def fail_cursor(*args, **kwargs):
        raise AssertionError("DB should not be used for mock evidence")

    monkeypatch.setattr("services.conflict.evidence_agent.get_cursor", fail_cursor)

    options = package_evidence(record, candidates)

    assert [option.source_url for option in options] == [
        "mock://uet/program-page",
        "mock://vnu/proposal-pdf",
    ]
    assert [option.trust_level for option in options] == [2, 3]


def test_package_evidence_keeps_options_when_db_enrichment_missing(monkeypatch):
    candidates = [
        candidate("https://uet.vnu.edu.vn/a", 120),
        candidate("https://vnu.edu.vn/b.pdf", 150),
    ]
    record = detect_quota_conflicts(candidates)[0]

    class Cursor:
        def execute(self, *args, **kwargs):
            return None

        def fetchone(self):
            return None

    class CursorContext:
        def __enter__(self):
            return Cursor()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("services.conflict.evidence_agent.get_cursor", lambda commit=False: CursorContext())

    options = package_evidence(record, candidates)

    assert len(options) == 2
    assert all(option.fetched_at is None for option in options)
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
pytest tests/services/conflict/test_evidence_agent.py -v
```

Expected: FAIL because module is missing.

- [ ] **Step 3: Implement evidence packaging**

Create `services/conflict/evidence_agent.py`:

```python
from typing import Dict, List, Optional

from agents.models import CandidateProgram
from ingestion.storage.db_connection import get_cursor
from services.conflict.models import ConflictRecord, EvidenceOption


def _candidate_by_source(candidates: List[CandidateProgram]) -> Dict[str, CandidateProgram]:
    mapping: Dict[str, CandidateProgram] = {}
    for candidate in candidates:
        for evidence in candidate.evidence:
            mapping[evidence.source_url] = candidate
    return mapping


def _is_mock_source(source_url: str, candidate: Optional[CandidateProgram]) -> bool:
    return source_url.startswith("mock://") or bool(
        candidate and candidate.metadata.get("mock_conflict")
    )


def _enrich_from_db(option: EvidenceOption, record: ConflictRecord) -> EvidenceOption:
    sql = """
        SELECT rd.fetched_at
        FROM canonical_admission_records car
        LEFT JOIN extracted_facts ef ON ef.id = car.extracted_fact_id
        LEFT JOIN raw_documents rd ON rd.id = ef.raw_document_id
        WHERE car.source_url = %s
          AND car.school_id = %s
          AND car.admission_year = %s
        LIMIT 1
    """
    with get_cursor(commit=False) as cur:
        cur.execute(sql, (option.source_url, record.school_id, record.admission_year))
        row = cur.fetchone()
    if row:
        option.fetched_at = row[0]
    return option


def package_evidence(
    record: ConflictRecord,
    raw_candidates: List[CandidateProgram],
) -> List[EvidenceOption]:
    candidates_by_source = _candidate_by_source(raw_candidates)
    packaged: List[EvidenceOption] = []
    for option in record.options:
        candidate = candidates_by_source.get(option.source_url)
        if _is_mock_source(option.source_url, candidate):
            packaged.append(option)
            continue
        try:
            packaged.append(_enrich_from_db(option, record))
        except Exception:
            packaged.append(option)
    return packaged
```

- [ ] **Step 4: Run tests**

Run:

```powershell
pytest tests/services/conflict/test_evidence_agent.py -v
```

Expected: PASS.

---

## Task 3: Comparison and Resolution Services

**Files:**
- Create: `services/conflict/comparison_agent.py`
- Create: `services/conflict/resolution_agent.py`
- Modify: `services/conflict_resolution_service.py`
- Create: `tests/services/conflict/test_comparison_agent.py`
- Create: `tests/services/conflict/test_resolution_agent.py`

- [ ] **Step 1: Write comparison tests**

Create `tests/services/conflict/test_comparison_agent.py`:

```python
from datetime import datetime

from services.conflict.comparison_agent import compare
from services.conflict.models import EvidenceOption


def option(value, trust=2, source="mock://a", confidence=0.9, fetched_at=None):
    return EvidenceOption(
        evidence_id=f"{source}|quota",
        source_url=source,
        trust_level=trust,
        confidence_score=confidence,
        fetched_at=fetched_at,
        value=value,
    )


def test_trust_level_can_be_decisive():
    report = compare([option(120, trust=2), option(150, trust=3, source="mock://b")])

    assert report.is_decisive is True
    assert report.ranked_options[0].value == 150
    assert report.decision_axes == ["trust_level"]


def test_corroboration_can_be_decisive():
    report = compare(
        [
            option(120, trust=2, source="mock://a"),
            option(150, trust=2, source="mock://b"),
            option(150, trust=2, source="mock://c"),
        ]
    )

    assert report.is_decisive is True
    assert report.ranked_options[0].value == 150
    assert "corroboration" in report.decision_axes


def test_all_tie_is_indecisive():
    report = compare([option(120, trust=2), option(150, trust=2, source="mock://b")])

    assert report.is_decisive is False
```

- [ ] **Step 2: Write resolution tests**

Create `tests/services/conflict/test_resolution_agent.py`:

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


def test_decisive_report_resolves_without_gateway():
    options = [option(120, trust=2), option(150, trust=3, source="mock://b")]

    def gateway_should_not_run(*args, **kwargs):
        raise AssertionError("Gateway should not run for decisive comparison")

    outcome = resolve(record(options), compare(options), gateway=gateway_should_not_run)

    assert outcome.status == "resolved"
    assert outcome.resolved_value == 150
    assert outcome.chosen_evidence.source_url == "mock://b"
    assert outcome.used_llm_tiebreaker is False


def test_indecisive_medium_gateway_result_stays_unresolved():
    options = [option(120, trust=2), option(150, trust=2, source="mock://b")]

    def gateway(*args, **kwargs):
        return {
            "chosen_source_url": "mock://b",
            "confidence": "medium",
            "rationale": "Tie remains uncertain.",
        }

    outcome = resolve(record(options), compare(options), gateway=gateway)

    assert outcome.status == "unresolved"
    assert outcome.resolved_value is None
    assert outcome.uncertainty_reason
```

- [ ] **Step 3: Run and verify failure**

Run:

```powershell
pytest tests/services/conflict/test_comparison_agent.py tests/services/conflict/test_resolution_agent.py -v
```

Expected: FAIL because modules are missing.

- [ ] **Step 4: Implement comparison**

Create `services/conflict/comparison_agent.py`:

```python
from collections import Counter
from typing import Any, List

from services.conflict.models import ComparisonReport, EvidenceOption


def _score(option: EvidenceOption, corroboration: Counter) -> tuple:
    return (
        option.trust_level if option.trust_level is not None else -1,
        corroboration[str(option.value)],
        option.fetched_at is not None,
        option.fetched_at,
        option.confidence_score if option.confidence_score is not None else -1.0,
    )


def compare(options: List[EvidenceOption]) -> ComparisonReport:
    if not options:
        return ComparisonReport(ranked_options=[], is_decisive=False, decision_axes=[])

    corroboration = Counter(str(option.value) for option in options)
    ranked = sorted(options, key=lambda option: _score(option, corroboration), reverse=True)
    if len(ranked) == 1:
        return ComparisonReport(ranked_options=ranked, is_decisive=True, decision_axes=["single_option"])

    first_score = _score(ranked[0], corroboration)
    second_score = _score(ranked[1], corroboration)
    if first_score == second_score:
        return ComparisonReport(ranked_options=ranked, is_decisive=False, decision_axes=[])

    axes = []
    if first_score[0] != second_score[0]:
        axes.append("trust_level")
    elif first_score[1] != second_score[1]:
        axes.append("corroboration")
    elif first_score[3] != second_score[3]:
        axes.append("recency")
    elif first_score[4] != second_score[4]:
        axes.append("confidence_score")

    return ComparisonReport(ranked_options=ranked, is_decisive=True, decision_axes=axes)
```

- [ ] **Step 5: Implement resolution**

Create `services/conflict/resolution_agent.py`:

```python
from typing import Callable, Optional

from services.conflict.models import ComparisonReport, ConflictRecord, EvidenceOption, ResolutionOutcome


GatewayFunc = Callable[..., dict]


def _unresolved(record: ConflictRecord, reason: str, used_llm: bool = False) -> ResolutionOutcome:
    return ResolutionOutcome(
        conflict_key=record.conflict_key,
        field_name=record.field_name,
        school_id=record.school_id,
        school_name=record.school_name,
        program_name=record.program_name,
        status="unresolved",
        rationale=reason,
        uncertainty_reason=reason,
        used_llm_tiebreaker=used_llm,
    )


def _find_option(report: ComparisonReport, source_url: str) -> Optional[EvidenceOption]:
    for option in report.ranked_options:
        if option.source_url == source_url:
            return option
    return None


def resolve(
    record: ConflictRecord,
    report: ComparisonReport,
    gateway: Optional[GatewayFunc] = None,
) -> ResolutionOutcome:
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

    if gateway is None:
        return _unresolved(record, "Comparison was not decisive.")

    try:
        response = gateway(record=record, report=report)
    except Exception:
        return _unresolved(record, "LLM tiebreaker failed.", used_llm=True)

    if response.get("confidence") != "high":
        return _unresolved(record, "LLM tiebreaker did not reach high confidence.", used_llm=True)

    chosen = _find_option(report, response.get("chosen_source_url", ""))
    if chosen is None:
        return _unresolved(record, "LLM tiebreaker chose an unknown source.", used_llm=True)

    return ResolutionOutcome(
        conflict_key=record.conflict_key,
        field_name=record.field_name,
        school_id=record.school_id,
        school_name=record.school_name,
        program_name=record.program_name,
        status="resolved",
        resolved_value=chosen.value,
        chosen_evidence=chosen,
        rejected_evidence=[option for option in report.ranked_options if option != chosen],
        rationale=response.get("rationale") or "Resolved by LLM tiebreaker.",
        decision_axes=["llm_tiebreaker"],
        used_llm_tiebreaker=True,
    )
```

- [ ] **Step 6: Run tests**

Run:

```powershell
pytest tests/services/conflict/test_comparison_agent.py tests/services/conflict/test_resolution_agent.py -v
```

Expected: PASS.

---

## Task 4: Rewrite Conflict Agent and Wire Graph

**Files:**
- Modify: `agents/conflict_agent.py`
- Modify: `graph.py`
- Create: `tests/agents/test_conflict_agent.py`

- [ ] **Step 1: Write failing conflict-agent tests**

Create `tests/agents/test_conflict_agent.py`:

```python
from agents.conflict_agent import conflict_agent
from agents.models import CandidateProgram, Evidence
from state import AgentState


def candidate(source_url, quota, trust):
    return CandidateProgram(
        candidate_id="vnu_uet:2026:cntt:thpt_score",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
        admission_method="thpt_score",
        quota={"value": quota, "unit": "students"},
        evidence=[
            Evidence(
                source_url=source_url,
                school_name="Dai hoc Cong nghe - DHQGHN",
                admission_year=2026,
                field_name="quota",
                normalized_value={"value": quota, "unit": "students"},
                trust_level=trust,
                confidence_score=0.9,
            )
        ],
    )


def test_conflict_agent_resolves_decisive_quota_conflict():
    state = AgentState(
        user_query="Tu van",
        retrieved_programs=[
            candidate("mock://uet/program-page", 120, 2),
            candidate("mock://vnu/proposal-pdf", 150, 3),
        ],
    )

    output = conflict_agent(state)

    assert len(output.conflict_records) == 1
    assert len(output.resolution_outcomes) == 1
    assert output.resolution_outcomes[0].status == "resolved"
    assert output.resolution_outcomes[0].resolved_value == 150
    assert output.conflicts == []


def test_conflict_agent_marks_unresolved_candidates_uncertain(monkeypatch):
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
        "quota" in candidate.data_uncertain_fields
        for candidate in output.retrieved_programs
    )
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
pytest tests/agents/test_conflict_agent.py -v
```

Expected: FAIL because current `conflict_agent` only merges flat strings.

- [ ] **Step 3: Implement `agents/conflict_agent.py`**

Replace the file with:

```python
from services.conflict.comparison_agent import compare
from services.conflict.detection import detect_quota_conflicts
from services.conflict.evidence_agent import package_evidence
from services.conflict.resolution_agent import resolve
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


def conflict_agent(state: AgentState):
    records = detect_quota_conflicts(state.retrieved_programs)
    outcomes = []

    for record in records:
        options = package_evidence(record, state.retrieved_programs)
        record.options = options
        report = compare(options)
        outcome = resolve(record, report)
        outcomes.append(outcome)
        if outcome.status == "unresolved":
            _mark_uncertain(state, record.conflict_key, record.field_name)

    state.conflict_records = records
    state.resolution_outcomes = outcomes
    state.conflicts = [
        outcome.rationale
        for outcome in outcomes
        if outcome.status == "unresolved" or outcome.used_llm_tiebreaker
    ]
    return state
```

- [ ] **Step 4: Wire `graph.py`**

Add import:

```python
from agents.conflict_agent import conflict_agent
```

Add node:

```python
builder.add_node("conflict", conflict_agent)
```

Replace edge:

```python
builder.add_edge("retrieve", "reason")
```

with:

```python
builder.add_edge("retrieve", "conflict")
builder.add_edge("conflict", "reason")
```

- [ ] **Step 5: Run tests**

Run:

```powershell
pytest tests/agents/test_conflict_agent.py -v
```

Expected: PASS.

---

## Task 5: Reasoning Downgrade for Uncertain Quota

**Files:**
- Modify: `services/reasoning_service.py`
- Modify: `tests/agents/test_reasoning_agent.py`

- [ ] **Step 1: Add failing test**

Append to `tests/agents/test_reasoning_agent.py`:

```python
def test_uncertain_quota_candidate_is_not_safe_band():
    state = AgentState(
        user_query="Tu van",
        student_profile=StudentProfile(total_score=29, subject_combination="A00"),
        retrieved_programs=[
            CandidateProgram(
                candidate_id="vnu_uet:2026:cntt:thpt_score",
                school_id="vnu_uet",
                school_name="Dai hoc Cong nghe - DHQGHN",
                admission_year=2026,
                program_id="cntt",
                program_name="Cong nghe thong tin",
                admission_method="thpt_score",
                subject_combinations=["A00"],
                data_uncertain_fields=["quota"],
            )
        ],
    )

    output = reasoning_agent(state)

    assert output.ranked_recommendations[0].band != "safe"
    assert "So lieu han ngach chua duoc xac nhan giua cac nguon." in output.ranked_recommendations[0].cautions
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
pytest tests/agents/test_reasoning_agent.py::test_uncertain_quota_candidate_is_not_safe_band -v
```

Expected: FAIL because uncertain quota is not handled.

- [ ] **Step 3: Update `services/reasoning_service.py`**

After `band = _score_to_band(score, has_missing_critical)`, add:

```python
        if "quota" in candidate.data_uncertain_fields:
            if band == "safe":
                band = "match"
            cautions.append("So lieu han ngach chua duoc xac nhan giua cac nguon.")
```

- [ ] **Step 4: Run tests**

Run:

```powershell
pytest tests/agents/test_reasoning_agent.py -v
```

Expected: PASS.

---

## Task 6: Verification Section in Final Answer

**Files:**
- Modify: `services/explanation_service.py`
- Modify: `agents/explanation_agent.py`
- Modify: `tests/agents/test_explanation_agent.py`

- [ ] **Step 1: Add failing explanation tests**

Append to `tests/agents/test_explanation_agent.py`:

```python
from services.conflict.models import EvidenceOption, ResolutionOutcome


def test_explanation_includes_data_verification_section_for_resolved_outcome():
    option = EvidenceOption(
        evidence_id="mock://vnu/proposal-pdf|quota",
        source_url="mock://vnu/proposal-pdf",
        trust_level=3,
        value=150,
    )
    state = AgentState(
        user_query="Tu van",
        resolution_outcomes=[
            ResolutionOutcome(
                conflict_key="vnu_uet:2026:cntt:thpt_score",
                field_name="quota",
                school_id="vnu_uet",
                school_name="Dai hoc Cong nghe - DHQGHN",
                program_name="Cong nghe thong tin",
                status="resolved",
                resolved_value=150,
                chosen_evidence=option,
                rationale="Resolved by deterministic comparison.",
                decision_axes=["trust_level"],
            )
        ],
    )

    output = explanation_agent(state)

    assert "## Xac minh du lieu" in output.final_answer
    assert "Cong nghe thong tin" in output.final_answer
    assert "150" in output.final_answer
    assert "Nguon mock: VNU proposal PDF" in output.final_answer
```

- [ ] **Step 2: Run and verify failure**

Run:

```powershell
pytest tests/agents/test_explanation_agent.py::test_explanation_includes_data_verification_section_for_resolved_outcome -v
```

Expected: FAIL because `explanation_agent` does not pass outcomes.

- [ ] **Step 3: Modify `services/explanation_service.py`**

Add import:

```python
from services.conflict.models import ResolutionOutcome
from services.conflict.source_labels import label_for_source
```

Change signature:

```python
def build_explanation(
    profile: StudentProfile,
    recommendations: List[RankedRecommendation],
    candidates: List[CandidateProgram],
    policy: Optional[PolicyDecision],
    resolution_outcomes: Optional[List[ResolutionOutcome]] = None,
) -> str:
```

Add helper:

```python
def _verification_lines(outcomes: List[ResolutionOutcome]) -> List[str]:
    if not outcomes:
        return []
    lines = ["## Xac minh du lieu"]
    for outcome in outcomes:
        if outcome.status == "resolved" and outcome.chosen_evidence:
            lines.append(
                f"- Han ngach nganh {outcome.program_name} tai {outcome.school_name}: "
                f"he thong tim thay nhieu nguon khac nhau. Su dung gia tri "
                f"{outcome.resolved_value} tu {label_for_source(outcome.chosen_evidence.source_url)} "
                f"vi {', '.join(outcome.decision_axes) or outcome.rationale}."
            )
        else:
            lines.append(
                f"- Han ngach nganh {outcome.program_name} tai {outcome.school_name}: "
                "thong tin mau thuan giua cac nguon. Ban nen xac minh truc tiep voi truong truoc khi dang ky."
            )
    return lines
```

Before `return "\n".join(lines)`, add:

```python
    lines.extend(_verification_lines(resolution_outcomes or []))
```

- [ ] **Step 4: Modify `agents/explanation_agent.py`**

Pass outcomes:

```python
        resolution_outcomes=state.resolution_outcomes,
```

- [ ] **Step 5: Run tests**

Run:

```powershell
pytest tests/agents/test_explanation_agent.py -v
```

Expected: PASS.

---

## Task 7: Graph Integration with Mock Retrieval

**Files:**
- Modify: `tests/e2e/test_advisory_flow.py`

- [ ] **Step 1: Add env-driven graph test**

Append to `tests/e2e/test_advisory_flow.py`:

```python
def test_graph_mock_retrieval_conflict_reaches_final_answer(monkeypatch):
    monkeypatch.setenv("ADVISORY_MOCK_CONFLICTS", "1")

    def fail_get_cursor(*args, **kwargs):
        raise AssertionError("DB should not be used by retrieval in mock mode")

    monkeypatch.setattr("services.retrieval_service.get_cursor", fail_get_cursor)

    from graph import graph
    from state import AgentState

    result = graph.invoke(
        AgentState(user_query="Tu van nganh CNTT UET nam 2026").dict()
    )

    assert "final_answer" in result
    assert "Xac minh du lieu" in result["final_answer"]
```

If the repo uses Pydantic v2, replace `.dict()` with `.model_dump()` following existing tests.

- [ ] **Step 2: Run focused e2e**

Run:

```powershell
pytest tests/e2e/test_advisory_flow.py -k mock -v
```

Expected: PASS. If graph invocation shape differs, adjust only the test setup to match existing tests in the file.

---

## Task 8: Slice Verification

**Files:**
- No edits.

- [ ] **Step 1: Run focused conflict tests**

Run:

```powershell
pytest tests/services/conflict tests/agents/test_conflict_agent.py tests/agents/test_reasoning_agent.py tests/agents/test_explanation_agent.py -v
```

Expected: PASS.

- [ ] **Step 2: Run graph tests**

Run:

```powershell
pytest tests/e2e/test_advisory_flow.py -v
```

Expected: PASS.

- [ ] **Step 3: Check diff, do not commit**

Run:

```powershell
git diff -- services/conflict agents graph.py services/reasoning_service.py services/explanation_service.py tests
git status --short
```

Expected: only slice-4 files plus prior slice files are modified/created. Do not run `git commit`.
