# Conflict-Aware Advisory V1 Design

## Summary

Build the Evidence / Comparison / Resolution multi-agent layer from the original `Agentic Admission Advisory` spec (§III "Conflict handling"), wire it into the advisory graph between retrieval and reasoning, and demonstrate it on a deliberately curated dataset of 2 Hanoi schools (HUST and VNU-UET) where the same program has conflicting **quota** values across an official website and a published admission proposal PDF. Add an opt-in mock retrieval mode (`ADVISORY_MOCK_CONFLICTS=1`) so the conflict-aware flow can be tested and demoed with stable synthetic `CandidateProgram` rows before real HUST/VNU-UET data is ready. Resolution rationale surfaces in the student-facing chat answer ("we found two reports of X; we trusted source A because…"). Freshness scoring, additional conflict types, and broader dataset scale-up are explicitly deferred to later phases.

This phase moves the project's central architectural claim — *"the system handles distributed, heterogeneous, conflicting admission data"* — from scaffolding to operational evidence on real data. For a thesis defense, the test of the architecture is whether it survives contact with real cross-source disagreement; this phase produces that survival evidence with the minimum surface area needed.

## Problem Statement

Conflict handling exists only at the surface today:

- `services/retrieval_service.py:detect_conflicts` emits flat strings like `"Quota conflict for X at Y"` — no structured conflict record, no evidence references, no per-source provenance carried forward.
- `agents/conflict_agent.py` exists but is not in the graph. The current graph runs profile → retrieve → reason → policy → explain. Conflicts only enter the system as inputs to `policy_agent`'s ambiguity-warning path.
- `services/conflict_resolution_service.py:resolve_conflicts_with_gateway` exists but is not called anywhere. It returns an unstructured `{resolution: str, uncertainty_reasons: [...]}` blob.
- The dataset is fixture-bound: one HUST program card. No real conflict has ever flowed through the pipeline.
- The conflict-aware graph depends on real conflicting rows that are slow to curate. Without an opt-in mock retrieval path, developers cannot run a stable end-to-end conflict demo until Postgres contains suitable HUST/VNU-UET records.

That means the central architectural claim of the project has scaffolding but no operational evidence. For a thesis demo this is the load-bearing weakness: the defense question "can you show this resolving a real conflict?" currently has no answer.

The phase closes that gap with the minimum surface area needed: structured conflict records, a deterministic-first Evidence/Comparison/Resolution agent layer, real ingested conflicting sources for 2 schools on one conflict type (quota), and visible rationale in the chat output.

## Goals

- Promote conflicts from flat strings to structured `ConflictRecord` objects that carry the conflicting field, the conflict key (school, year, program, method), and the candidate evidence options with full source provenance.
- Add an Evidence agent that packages candidate evidence rows for a given conflict with normalized provenance metadata.
- Add a Comparison agent that ranks evidence options using deterministic rules (authority/trust level, corroboration, recency, value-type consistency).
- Add a Resolution agent that applies the resolution policy and returns either a decisive resolution (`resolved_value`, `chosen_evidence_id`, `rationale`) or an explicit `unresolved` state with an uncertainty reason. The LLM is used only as a tiebreaker for marginal cases, behind the existing inference gateway, and only flips to resolved on `confidence == "high"`.
- Wire conflict resolution into the advisory graph as a node between `retrieve` and `reason`. Downstream reasoning sees either resolved values or candidates marked `data_uncertain`.
- Curate a real dataset of 2 Hanoi schools (HUST + VNU-UET) where the same program's quota differs across two official sources, in admission year 2026. Ingest both through the existing pipeline.
- Add an opt-in mock retrieval mode controlled by env/config (`ADVISORY_MOCK_CONFLICTS=1`) that returns 2-3 synthetic `CandidateProgram` rows with the same `(school_id, admission_year, program_id, admission_method)` and different quota values, without opening a DB connection.
- Surface resolution rationale in the chat-facing final answer when a conflict was resolved or left unresolved, in Vietnamese, via deterministic templates.
- Block candidates with uncertain quota from the top recommendation band but still show them in a lower band with a clear caution.
- Provide unit tests for each new agent and an integration test that proves a real ingested conflict survives end-to-end into the explanation.

## Non-Goals

- Freshness scoring beyond simple recency comparison. No field-level versioning, no `last_verified_at`, no decay function. Deferred to a later phase.
- Conflict types other than **quota**. Subject-combination, deadline, conditions, and tuition conflicts stay in the existing string-emitting path or are simply not raised.
- Broader ingestion coverage. Only HUST and VNU-UET are curated for this phase. No fanpage/Facebook ingestion, no scraping infrastructure expansion.
- Rewriting the ingestion pipeline. Reuse the existing fetcher / parser / normalization / db_writer layers. Tune parsers where the second school requires it; do not redesign them.
- Refactoring the advisory graph beyond inserting one node. The profile / retrieve / reason / policy / explain shape stays the same.
- Replacing `services/conflict_resolution_service.py` entirely. It becomes a structured tiebreaker tool the Resolution agent can call; it does not become the primary resolution mechanism.
- Building an operator console to inspect conflicts. Operators read the database directly for this phase.
- UI changes beyond what's needed to render the resolution rationale (no new panels, no new pages, no structured recommendation cards).
- Retiring the legacy `state.conflicts: List[str]` field. It survives in this phase as a compatibility shim populated only by unresolved or LLM-tiebroken outcomes.
- Treating mock conflicts as evaluation data. The mock path is for unit/integration tests, local demos, and development unblock only; it is not evidence that the real-data thesis claim has been satisfied.

## Recommended Approach

The system should add one new node (`conflict`) to the advisory graph between retrieval and reasoning, owning detection and resolution of conflicts produced by the existing ingestion pipeline. Detection promotes flat strings to structured records. Comparison runs deterministically over evidence options. Resolution applies a deterministic decision and falls back to an LLM tiebreaker only for marginal cases, with a conservative high-confidence threshold to flip uncertainty to resolution.

This is preferred over a single combined "conflict-handler" agent because the original architecture document explicitly distinguishes Evidence, Comparison, and Resolution responsibilities, and keeping them separate matches the thesis story and makes each independently testable.

It is preferred over an LLM-led resolution path because (a) the Gemini-backbone design principle is "deterministic logic first, LLM for interpretation," and (b) the defense answer to "how does it decide?" should be a readable rule set, not an opaque prompt.

The retrieval mock should live at the retrieval-service boundary, not inside the conflict node. `retrieval_agent` should continue to call `fetch_candidates(filters=...)`; `fetch_candidates` should check `ADVISORY_MOCK_CONFLICTS` before constructing SQL and return synthetic candidates when the flag is truthy. This keeps the graph, conflict detection, comparison, resolution, reasoning, policy, and explanation layers exercising the same runtime path in tests and demos. It also keeps production behavior obvious: when the flag is unset, retrieval uses Postgres exactly as it does today.

## Architecture

### Component map

```
[ingestion pipeline]            (existing)
        |
        v
canonical_admission_records     (existing, multi-row per (school, year, program, method) when sources differ)
        |
        v
+----------------------------------------------------------------+
| advisory graph (LangGraph)                                     |
|                                                                |
|   profile -> retrieve -> conflict -> reason -> policy -> explain
|                            ^^^^^^^                             |
|                            (NEW node)                          |
+----------------------------------------------------------------+
        |
        v
ConversationService / run_dispatcher  (existing)
        |
        v
chat UI                                (existing)
```

The single new node is `conflict`. Everything upstream (retrieval) and downstream (reasoning, policy, explanation) stays in place; conflict resolution becomes a separate, testable concern instead of being smeared across `detect_conflicts` calls in `retrieval_agent` and ambiguity warnings in `policy_agent`.

### New modules

- `agents/conflict_agent.py` — already exists as a stub; gets rewritten as the orchestrator for the conflict node.
- `services/mock_retrieval.py` — new small module returning stable synthetic `CandidateProgram` rows when `ADVISORY_MOCK_CONFLICTS=1`. It has no database dependency and is imported only by `services/retrieval_service.py`.
- `services/conflict/` — new package containing:
  - `models.py` — `ConflictRecord`, `EvidenceOption`, `ComparisonReport`, `ResolutionOutcome`.
  - `detection.py` — replaces the string-emission logic in `retrieval_service.detect_conflicts` with structured `ConflictRecord` construction. Groups candidates by `(school_id, admission_year, program_id_or_name, admission_method)` and, for the quota field, emits one `ConflictRecord` per group when distinct quota values exist.
  - `evidence_agent.py` — `package_evidence(record) -> List[EvidenceOption]`. Enriches each option with provenance not present in the `CandidateProgram`'s `Evidence` object: `fetched_at` joined from `raw_documents` via `extracted_facts.raw_document_id`, `is_official` and `parser_profile` joined from `source_registry`. See "Evidence enrichment join path" below. One SQL query per option; conflicts are few per session so no batching needed in this phase.
  - `comparison_agent.py` — `compare(options) -> ComparisonReport`. Fully deterministic, no LLM call.
  - `resolution_agent.py` — `resolve(record, report) -> ResolutionOutcome`. Deterministic decision when the comparison report is decisive; LLM tiebreaker only otherwise, with conservative high-confidence threshold.
  - `source_labels.py` — small helper that maps canonical hostnames to human-readable Vietnamese labels for chat surfacing.

- `services/conflict_resolution_service.py` — kept; its prompt is restructured to return JSON with `chosen_source_url`, `confidence` (`"high" | "medium" | "low"`), and `rationale`, so the Resolution agent can map back to a structured outcome.

### Data model

```python
# services/conflict/models.py

class EvidenceOption(BaseModel):
    evidence_id: str             # synthesized: source_url + field
    source_url: str
    trust_level: Optional[int]
    fetched_at: Optional[datetime]
    confidence_score: Optional[float]
    value: Any                   # the conflicting value (e.g., int quota)

class ConflictRecord(BaseModel):
    conflict_key: str            # "school_id:year:program:method"
    field_name: str              # "quota" (only quota in this phase)
    school_id: str
    school_name: str
    program_name: str
    admission_method: Optional[str]
    options: List[EvidenceOption]

class ComparisonReport(BaseModel):
    ranked_options: List[EvidenceOption]
    is_decisive: bool
    decision_axes: List[str]     # e.g., ["trust_level", "corroboration"]

class ResolutionOutcome(BaseModel):
    status: Literal["resolved", "unresolved"]
    resolved_value: Optional[Any]
    chosen_evidence: Optional[EvidenceOption]
    rejected_evidence: List[EvidenceOption] = []
    rationale: str
    uncertainty_reason: Optional[str] = None
```

### Graph state changes

`state.py:AgentState` adds two fields:

- `conflict_records: List[ConflictRecord]` — structured conflicts produced by the conflict node's detection step.
- `resolution_outcomes: List[ResolutionOutcome]` — outcomes from the conflict node, one per record.

`state.conflicts: List[str]` is kept as a backwards-compatibility shim for `policy_agent.evaluate_policy_guardrails`. Populated only by unresolved and LLM-tiebroken outcomes — deterministically resolved cases do not populate it.

`agents/models.py:CandidateProgram` adds one new optional field:

- `data_uncertain_fields: List[str] = []` — populated by the conflict node when a field's conflict couldn't be resolved, so downstream reasoning and explanation can flag it.

### Wiring into the graph

`graph.py` adds the conflict node:

```python
builder.add_node("conflict", conflict_agent)
builder.add_edge("retrieve", "conflict")
builder.add_edge("conflict", "reason")
```

`retrieval_agent`'s call to `detect_conflicts` is removed (the string-emission logic dies with it). The conflict node owns detection + resolution.

`policy_agent` keeps its ambiguity escalation. Its input becomes structured: it reads `state.resolution_outcomes` indirectly via the legacy `state.conflicts` shim, which only fires the ambiguity path when conflicts genuinely remain.

`explanation_agent` reads `state.resolution_outcomes` and, when any resolved or unresolved outcomes exist, includes a Vietnamese "Xác minh dữ liệu" section in `final_answer`.

### Mock retrieval mode

Mock retrieval is an opt-in test/demo source for `state.retrieved_programs`; it is not a second conflict detector and it does not write to the database.

**Config surface**

- Env var: `ADVISORY_MOCK_CONFLICTS=1`
- Truthy values: `1`, `true`, `yes`, `on` (case-insensitive)
- Default: disabled
- Documentation: add the var to `.env.example` with a comment that it is local/test/demo only

**Runtime placement**

`services/retrieval_service.py:fetch_candidates(filters, limit=100)` starts with:

```python
if mock_conflicts_enabled():
    return build_mock_conflict_candidates(filters=filters, limit=limit)
```

Only after this guard does it build SQL or call `get_cursor`. This is the key guarantee: when mock mode is enabled, the advisory flow does not touch Postgres for retrieval.

`retrieval_agent` remains thin:

1. Build filters from the profile and admission year.
2. Call `fetch_candidates(filters=filters)`.
3. Apply the existing subject-combination filter.
4. Store `state.retrieved_programs`.

The conflict-aware node then receives synthetic candidates through the same state field it receives real DB candidates from. This exercises the same detection, evidence packaging, comparison, resolution, reasoning, policy, and explanation code paths.

**Mock candidate shape**

`build_mock_conflict_candidates` returns 2-3 `CandidateProgram` objects with:

- Same `school_id`, `admission_year`, `program_id`, and `admission_method`.
- Same `candidate_id` conflict key shape as production retrieval currently uses. If production dedup later requires unique row IDs, append a source suffix only in a separate `source_record_id`/metadata field; do not change conflict grouping.
- Different `quota` values, normalized to the same dict shape, for example `{"value": 120, "unit": "students"}` and `{"value": 150, "unit": "students"}`.
- Distinct `Evidence.source_url`, `Evidence.trust_level`, and `Evidence.confidence_score` values so the Comparison agent can resolve deterministically.
- `metadata["mock_conflict"] = True` and `metadata["mock_dataset"] = "advisory_conflict_v1"` so logs/tests can identify synthetic candidates without depending on source URLs.

Recommended stable fixture:

```python
[
    CandidateProgram(
        candidate_id="vnu_uet:2026:cntt:thpt_score",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
        admission_method="thpt_score",
        subject_combinations=["A00", "A01"],
        quota={"value": 120, "unit": "students"},
        evidence=[
            Evidence(
                source_url="mock://uet/program-page",
                school_name="Dai hoc Cong nghe - DHQGHN",
                admission_year=2026,
                field_name="quota",
                normalized_value={"value": 120, "unit": "students"},
                trust_level=2,
                confidence_score=0.86,
            )
        ],
        metadata={"mock_conflict": True, "mock_dataset": "advisory_conflict_v1"},
    ),
    CandidateProgram(
        candidate_id="vnu_uet:2026:cntt:thpt_score",
        school_id="vnu_uet",
        school_name="Dai hoc Cong nghe - DHQGHN",
        admission_year=2026,
        program_id="cntt",
        program_name="Cong nghe thong tin",
        admission_method="thpt_score",
        subject_combinations=["A00", "A01"],
        quota={"value": 150, "unit": "students"},
        evidence=[
            Evidence(
                source_url="mock://vnu/proposal-pdf",
                school_name="Dai hoc Cong nghe - DHQGHN",
                admission_year=2026,
                field_name="quota",
                normalized_value={"value": 150, "unit": "students"},
                trust_level=3,
                confidence_score=0.94,
            )
        ],
        metadata={"mock_conflict": True, "mock_dataset": "advisory_conflict_v1"},
    ),
]
```

A third candidate may be included to exercise corroboration, for example another source reporting `150` with trust level 2. Keep the default fixture deterministic and small; tests should not depend on random quota values.

**Filter behavior**

The mock builder respects only the filters needed to keep local demos intuitive:

- `admission_year`: use the requested year when present, defaulting to the configured admission year.
- `preferred_schools`: if present and it excludes the mock `school_id`, return `[]`.
- `preferred_majors`: if present and it excludes both the mock `program_id` and a simple name match, return `[]`.
- `subject_combination`: leave filtering to `retrieval_agent`, matching the production path.

This keeps the mock path close enough to production retrieval for demos without reimplementing SQL semantics.

**Evidence enrichment in mock mode**

The Evidence agent must not assume every `EvidenceOption.source_url` can be joined back to `canonical_admission_records`. When the source URL starts with `mock://` or the candidate metadata marks it as a mock conflict, enrichment should use the provenance already present on the `CandidateProgram.evidence` object and skip DB joins. Missing `fetched_at` remains acceptable; Comparison falls through to trust and confidence axes.

**Failure and safety behavior**

- If mock mode is enabled, retrieval failures from Postgres cannot occur because retrieval does not open a cursor.
- If mock mode returns `[]` because filters exclude the mock fixture, the graph behaves like a normal no-result retrieval.
- Production deployments should leave the env var unset. No database query, schema migration, or ingestion behavior changes because of the mock module itself.

### Required schema change

The current `canonical_admission_records` schema has `UNIQUE(school_id, admission_year, program_id, admission_method)` (`db/migrations/005_canonical_programs.sql`) and `save_canonical_records` upserts on that exact tuple (`ingestion/storage/db_writer.py`). The effect is that the second source for the same logical program overwrites the first — the conflict signal the design depends on is actively destroyed by the writer.

This phase must add a new migration (`db/migrations/010_canonical_records_per_source.sql`) that:

1. Drops the existing `UNIQUE(school_id, admission_year, program_id, admission_method)` constraint.
2. Adds `UNIQUE(school_id, admission_year, program_id, admission_method, source_url)` — uniqueness per source instead of per logical program.

And update `ingestion/storage/db_writer.py:save_canonical_records` to use the new conflict target:

```sql
ON CONFLICT (school_id, admission_year, program_id, admission_method, source_url)
DO UPDATE SET ...
```

After this change, re-running ingestion for the same source updates that source's row, but distinct sources for the same logical program coexist as separate rows. The existing retrieval query already orders by `source_trust_level DESC NULLS LAST, confidence_score DESC NULLS LAST`, so multiple rows surface naturally in retrieval results — no retrieval-side change is needed.

### Evidence enrichment join path

The Evidence agent's enrichment uses this join chain to populate `fetched_at`, `is_official`, and `parser_profile`:

```sql
SELECT
  rd.fetched_at,
  sr.is_official,
  sr.parser_profile
FROM canonical_admission_records car
JOIN extracted_facts ef ON ef.id = car.extracted_fact_id
JOIN raw_documents rd ON rd.id = ef.raw_document_id
LEFT JOIN source_registry sr ON sr.source_id = rd.source_id
WHERE car.source_url = %s
  AND car.school_id = %s
  AND car.admission_year = %s
```

`raw_documents.fetched_at` is the right column for the recency axis (it reflects when the source was retrieved, not when extraction was performed). Missing rows along the join chain produce `None` enrichment fields — the Comparison agent treats `None` recency as "unknown" and falls through to the next tiebreaker.

### What stays untouched

- The `services/inference/` gateway, retry, and telemetry layer. Comparison is deterministic; only the Resolution tiebreaker uses the gateway, through the existing `resolve_conflicts_with_gateway` entry point.
- `services/chat/*` — conversation service, run dispatcher, repository. The conflict-aware advisory still produces a single `final_answer` string that flows back through the existing chat surface.
- The ingestion pipeline structure beyond the writer-side conflict-target change. The only ingestion work besides that is data curation (see Dataset Curation), not architectural changes.
- The chat UI. It continues to render `final_answer` as the assistant result turn.

## Dataset Curation

### Target dataset

- **2 schools: HUST and VNU-UET (Đại học Công nghệ, ĐHQGHN).** HUST is already partially plumbed (1 program fixture). VNU-UET publishes both an admission homepage at `uet.vnu.edu.vn` and is covered by the ĐHQGHN-wide admission proposal PDF — that's a legitimate cross-source pair (school's own program page vs. parent university's official proposal).
- **3-5 programs per school** that have observable quota conflicts.
- **One conflict type: quota.** Other extracted fields are ingested and stored but conflicts on them are out of scope for this phase.
- **One admission year: 2026.** No historical comparison needed.

### Pre-flight check (before any code)

Before committing parser time to VNU-UET, the implementer manually inspects both sources and confirms that:

1. Both sources are reachable and parseable in principle (the website renders without auth; the PDF is text-based, not scanned).
2. At least 3 programs have a numeric quota that differs across the two sources.
3. The programs can be aligned by name across the two sources without ambiguous matching (i.e., the program name in the ĐHQGHN proposal and on UET's site refers unambiguously to the same canonical program).

If pre-flight fails, see "Risks and bail-outs" below.

### Ingestion work expected

- **Source registry rows.** Add entries for VNU-UET's admission homepage, program pages, and the ĐHQGHN proposal PDF, with appropriate trust levels (`is_official=true`, proposal PDF priority > admission homepage > program page, matching existing source-registry conventions).
- **Parser work.**
  - HUST reuses `ingestion/parsers/hust_program_parser.py`.
  - VNU-UET HTML: try `html_parser.py` with parser-profile tuning first. If the HTML structure is regular enough, no new parser is needed. Otherwise add a thin school-specific parser following the `hust_program_parser.py` shape.
  - ĐHQGHN proposal PDF: reuse `ingestion/parsers/pdf_parser.py`. The risk is table extraction quality.
- **Normalization.** Program name → canonical program mapping must work for VNU-UET. The existing `programs.json` dictionary may need 3-5 new entries.
- **Storage.** No schema changes. Both sources land as separate `extracted_facts` rows for the same logical key, and both materialize as separate `canonical_admission_records` rows — exactly the signal the conflict node consumes.

### Acceptance criteria for the dataset

Before agent work begins, the dataset is "done" when:

- `canonical_admission_records` contains **at least 3 program-method tuples** where the same `(school_id, admission_year, program_id_or_name, admission_method)` key appears in 2 distinct rows with different quota values.
- Each row has populated `source_url`, `source_trust_level`, and the equivalent of `fetched_at` (from `extracted_facts`).
- A spot-check SQL query confirms the rows look right.

This is the only hard gate between dataset and agent work. If the dataset doesn't produce conflicts, the agent layer has nothing to demonstrate on.

### Dataset policy: no synthetic data in the evaluation dataset

- **Evaluation dataset (`canonical_admission_records` in Postgres):** only real ingested rows. No exceptions, no flagged "illustrative" rows mixed in.
- **Test fixtures (`tests/services/conflict/fixtures/`):** synthetic is fine and expected. They're clearly separated from the evaluation dataset and used by unit/integration tests.
- **Runtime mock retrieval (`ADVISORY_MOCK_CONFLICTS=1`):** synthetic is allowed because it bypasses Postgres entirely and returns in-memory `CandidateProgram` objects. It is acceptable for local development, automated graph tests, and fallback demos that prove the conflict-aware control flow. It is not acceptable as the real-data phase-completion gate.
- **Demo-only examples (if needed for a presentation):** prefer the runtime mock retrieval path over inserting tagged demo rows. If a separate fixture file is still needed, it must stay outside `canonical_admission_records` and must never be queried by the evaluation path.
- **If real curation produces fewer than the target organic conflicts:** the phase does not ship reduced. Re-curate (add a third school, swap source pairs) or extend the timeline. Failing loudly is the bail-out.

### Risks and bail-outs

- **Risk: ĐHQGHN proposal PDF parser produces poor table extraction.** Bail-out: switch to two HTML sources for VNU-UET (UET program page vs. an HTML form of the ĐHQGHN admission announcement, if one exists). Still real data, no synthetic.
- **Risk: Fewer than 3 organic quota conflicts after curating HUST + VNU-UET.** Bail-out: add a third school (NEU or FTU) and re-run pre-flight. Slip timeline rather than synthesize.
- **Risk: Program-name alignment between UET site and ĐHQGHN proposal is too ambiguous.** Pre-flight explicitly checks this. If it fails, swap school before parser work begins.
- **Risk: Ingestion takes longer than 1 week.** Bail-out: cut target to 2 organic conflicts (still real). If even 2 aren't reachable, the phase reschedules — it does not ship.

## Conflict + Resolution Flow

### Pre-conditions on entry to the conflict node

- `state.retrieved_programs` is populated by `retrieval_agent`. Multiple `CandidateProgram` rows may share the same `(school_id, admission_year, program_id_or_name, admission_method)` tuple when sources disagree.
- When `ADVISORY_MOCK_CONFLICTS=1`, those rows may be in-memory synthetic candidates from `services/mock_retrieval.py`; the conflict node should treat them exactly like DB-backed candidates except that provenance enrichment must not require SQL joins.
- `state.conflict_records` is empty.
- `state.resolution_outcomes` is empty.

### Step 1 — Detect

`services/conflict/detection.py:detect_quota_conflicts(candidates) -> List[ConflictRecord]`:

1. Group candidates by `(school_id, admission_year, program_id or program_name, admission_method)`.
2. For each group with >= 2 candidates, inspect the `quota` field:
   - Normalize each `quota` dict to a comparable scalar via `_normalize_quota_value(quota_dict)`. If quota shape is heterogeneous, treat it as conflict-eligible.
   - If at least 2 distinct values exist, build one `ConflictRecord` with one `EvidenceOption` per candidate row (not per distinct value). The Comparison agent uses corroboration as a tiebreaker axis, so preserving all rows matters.
3. Return the list.

### Step 2 — Package evidence

`services/conflict/evidence_agent.py:package_evidence(record, raw_candidates) -> List[EvidenceOption]`:

Enriches each option with provenance not in the `CandidateProgram`'s `Evidence` object: `fetched_at` from `extracted_facts`, `is_official` from the source registry, `parser_profile` for traceability. One SQL query per option, joining `extracted_facts` → `discovered_resources` → `source_registry`. Missing rows produce `None` enrichment fields, never exceptions.

### Step 3 — Compare

`services/conflict/comparison_agent.py:compare(options) -> ComparisonReport`. Deterministic, axes applied in order:

1. **Authority (trust_level).** Higher trust_level wins. Strict numeric comparison.
2. **Corroboration.** If two or more options report the same value, that value gets a corroboration bonus: its representative is treated as if its trust_level were `max(actual trust_level, second-highest single-source trust_level)`. This lets two mid-trust agreements outweigh a single high-trust outlier — the rule that handles the case where the proposal PDF lags behind website updates.
3. **Recency (`fetched_at`).** More recently fetched wins. Tiebreaker only.
4. **Confidence score.** Final tiebreaker.

`is_decisive` is true when the top-ranked option strictly dominates the second-ranked option on at least one earlier axis without losing on any earlier axis.

`decision_axes` is the ordered list of axes that contributed to the decisive ranking, used for the explanation template.

### Step 4 — Resolve

`services/conflict/resolution_agent.py:resolve(record, report) -> ResolutionOutcome`:

1. If `report.is_decisive`:
   - Return `status="resolved"`, `resolved_value = report.ranked_options[0].value`, `chosen_evidence = report.ranked_options[0]`, `rejected_evidence = report.ranked_options[1:]`, `rationale` built deterministically from `decision_axes` and the chosen source.
2. If not decisive:
   - Call `services/conflict_resolution_service.resolve_conflicts_with_gateway` with a restructured payload `{conflict_record, comparison_report}` and an updated prompt asking for JSON `{chosen_source_url: str | null, confidence: "high" | "medium" | "low", rationale: str}`.
   - If the gateway returns `chosen_source_url` matching one of the options AND `confidence == "high"`: return `resolved` with that option chosen and rationale prefixed `"LLM tiebreaker: "`.
   - Otherwise (medium/low confidence, invalid `chosen_source_url`, parse failure, or gateway raises): return `status="unresolved"`, `chosen_evidence=None`, `rationale = "Conflicting authoritative sources could not be reconciled deterministically"`, `uncertainty_reason = "conflict_unresolved_quota"`.

The LLM tiebreaker is conservative by design. The defense story is that the system declines to fabricate authority — it explicitly flags uncertainty when sources genuinely disagree without a deterministic tiebreaker.

### Step 5 — Reconcile candidate list

After all conflicts resolve, the conflict node mutates `state.retrieved_programs`:

- For each **resolved** outcome: collapse the duplicate candidates for that conflict_key into one representative `CandidateProgram` carrying the resolved quota value. The representative keeps the evidence list of the chosen option; rejected options' evidence is dropped from the candidate but remains in the `ResolutionOutcome` for explanation.
- For each **unresolved** outcome: keep all duplicate candidates and set `data_uncertain_fields = ["quota"]` on each.

### Step 6 — Populate state

- `state.conflict_records = [...]`
- `state.resolution_outcomes = [...]`
- `state.conflicts` (legacy) is populated only from unresolved or LLM-tiebroken outcomes' rationales, preserving the policy_agent's input distribution: ambiguity-interpretation fires exactly when conflicts genuinely remain.

### Post-conditions

- `state.conflict_records` reflects every detected quota conflict.
- `state.resolution_outcomes` has exactly one outcome per conflict record.
- `state.retrieved_programs` is deduplicated for resolved conflicts and uncertainty-flagged for unresolved ones.
- `state.conflicts` contains only unresolved or LLM-tiebroken cases.

## User-Facing Surfacing

### Where the surfacing happens

Two existing agents read `state.resolution_outcomes` and emit user-visible text:

- `explanation_agent` — appends a "Xác minh dữ liệu" paragraph to `state.final_answer` when any outcomes exist (resolved or unresolved).
- `policy_agent` — only fires on unresolved outcomes via the legacy `state.conflicts` shim, adding warnings to `state.policy_decision.warnings`. The explanation agent already merges policy warnings into the final answer.

No new agent, no new graph node, no new chat-API field. The chat shell keeps rendering `final_answer` as the assistant result turn.

### Explanation agent changes

`agents/explanation_agent.py` and `services/explanation_service.py:build_explanation` get one new responsibility: when `state.resolution_outcomes` is non-empty, append a `## Xác minh dữ liệu` section to the final answer in Vietnamese, **rendered from deterministic templates** (not LLM-generated). Templates ensure the explanation cannot contradict the actual resolution rationale.

Format per outcome:

**Resolved (deterministic):**
> *Hạn ngạch ngành [program_name] tại [school_name]: hệ thống tìm thấy nhiều nguồn báo cáo khác nhau. Chúng tôi sử dụng giá trị [resolved_value] từ [chosen source label] vì [decision_axes rendered in Vietnamese]. Nguồn khác báo cáo [rejected values].*

**Resolved (LLM tiebreaker):**
Same as above with the rationale prefix replaced by *"Hệ thống cần đối chiếu thêm để quyết định"* and the chosen source explicitly named.

**Unresolved:**
> *Hạn ngạch ngành [program_name] tại [school_name]: hệ thống tìm thấy thông tin mâu thuẫn giữa các nguồn ([list of source labels with values]). Bạn nên xác minh trực tiếp với trường trước khi đăng ký.*

Source labels are rendered from `EvidenceOption.source_url` mapped through `services/conflict/source_labels.py` — a small dictionary plus URL host extraction. Unknown hostnames fall back to a label using the hostname itself; no crash, no "undefined".

### Reasoning agent changes

`agents/reasoning_agent.py` and `services/reasoning_service.py:reason_candidates` learn one rule: when a candidate has `data_uncertain_fields` non-empty, that candidate is blocked from the top **"suitable" / strong recommendation** band. It can still appear in lower-confidence bands (e.g., "cân nhắc thêm") with the uncertainty visibly reflected in `RankedRecommendation.cautions`.

The Vietnamese caution string: *"Số liệu hạn ngạch chưa được xác nhận giữa các nguồn."* The explanation agent already renders cautions, so no further wiring is needed.

This is the part of the design where the recommendation itself visibly reflects data integrity — not just the final paragraph. A contested quota number changes how confidently the system recommends the program.

### Policy agent — unchanged in this phase

`policy_agent.evaluate_policy_guardrails` already reads `state.conflicts: List[str]` and runs `interpret_policy_ambiguity` when conflicts exist. The legacy compatibility shim from Step 6 (only unresolved/LLM-tiebroken outcomes populate `state.conflicts`) means the policy agent's ambiguity path fires exactly when conflicts genuinely remain. No code change in `policy_agent.py`.

### What stays out

- No structured JSON output for the chat client. The chat UI continues to render `final_answer` as text.
- No interactive "show me the sources" affordance. Source labels are inlined into the text.
- No edit-time conflict UI for operators. Operator surfacing is deferred per non-goals.
- No translation layer. Vietnamese strings are baked into the explanation service.

## Testing Strategy

### Unit tests — synthetic fixtures, fast, isolated

- `tests/services/test_mock_retrieval.py`
  - Env disabled -> `fetch_candidates` follows the DB path; mock builder is not called.
  - Env enabled -> `fetch_candidates` returns 2-3 candidates without calling `get_cursor`.
  - Returned candidates share `(school_id, admission_year, program_id, admission_method)` and contain at least 2 distinct quota values.
  - `preferred_schools` excluding the mock school returns `[]`.
  - `preferred_majors` excluding the mock program returns `[]`.
  - Evidence has distinct source URLs, trust levels, and confidence scores.
- `tests/services/conflict/test_detection.py`
  - Single group with 2 candidates and distinct quotas → 1 `ConflictRecord` with 2 options.
  - Single group with 3 candidates where 2 agree on value A and 1 reports B → 1 record, 3 options.
  - Single group with identical quotas → no record.
  - Multiple groups → multiple records, no cross-contamination.
  - Heterogeneous quota dict shapes → conflict-eligible (treated as different normalized values).
- `tests/services/conflict/test_evidence_agent.py`
  - Mocks the SQL join layer. Given an option with a `source_url`, returns the option enriched with `fetched_at`, `is_official`, `parser_profile`.
  - Missing extracted_facts row → option's enrichment fields stay `None`; no exception.
- `tests/services/conflict/test_comparison_agent.py`
  - Single decisive axis: trust_level 3 vs. 1 → decisive, axes = `["trust_level"]`.
  - Corroboration: 2 options at trust_level 2 agreeing on value A vs. 1 option at trust_level 3 reporting B → A wins via corroboration; axes include `"corroboration"`.
  - All-tie: same trust_level, same recency, same confidence → `is_decisive = false`.
  - Recency tiebreaker: equal trust_level, different `fetched_at` → decisive on recency.
  - Confidence-only tiebreaker fires only when earlier axes tie.
- `tests/services/conflict/test_resolution_agent.py`
  - Decisive report → `resolved` outcome with deterministic rationale; gateway never called (mock asserts).
  - Indecisive + gateway returns `confidence="high"` with valid `chosen_source_url` → `resolved` with LLM-tiebreaker rationale.
  - Indecisive + gateway returns `confidence="medium"` → `unresolved`.
  - Indecisive + gateway returns invalid `chosen_source_url` → `unresolved`; do not silently pick.
  - Indecisive + gateway raises → `unresolved`; failure does not propagate.
- `tests/agents/test_conflict_agent.py`
  - End-to-end node test with synthetic `state.retrieved_programs`. Validates: `conflict_records`, `resolution_outcomes`, `retrieved_programs` collapse on resolved, `data_uncertain_fields` set on unresolved, legacy `state.conflicts` populated only for unresolved/LLM-tiebroken.
- `tests/services/conflict/test_source_labels.py`
  - Known hostnames → known Vietnamese labels.
  - Unknown hostname → fallback label using the hostname itself.

### Agent-integration tests — synthetic state, real graph wiring

- `tests/agents/test_reasoning_agent.py` (extend existing)
  - Candidate with `data_uncertain_fields = ["quota"]` is not in the top "suitable" band; appears in a lower band with the Vietnamese caution string present in `RankedRecommendation.cautions`.
- `tests/agents/test_explanation_agent.py` (extend existing)
  - `state.resolution_outcomes` non-empty → `final_answer` contains the `## Xác minh dữ liệu` section.
  - Resolved outcome → section contains the resolved value and the chosen source label.
  - Unresolved outcome → section contains both source labels with their reported values and the "verify with the school" sentence.
  - Empty outcomes → no verification section emitted.
- `tests/agents/test_policy_agent.py` (extend existing)
  - Only unresolved/LLM-tiebroken outcomes trigger `interpret_policy_ambiguity`. Deterministic-resolved cases do not.

### Graph integration test — real LangGraph wiring, synthetic data, deterministic Gemini stub

- `tests/e2e/test_advisory_flow.py` (extend existing)
  - Fixture where seeded `retrieved_programs` contains 2 rows for the same conflict key with different quotas. Run the full graph. Assert: `final_answer` contains the verification section AND the recommendation reflects the resolved value AND `policy_decision.warnings` is empty (deterministic resolution).
  - Parallel fixture where the comparison is forced indecisive (equal trust levels and recency). Stub the LLM tiebreaker to return `confidence="medium"`. Assert: `final_answer` contains the unresolved verification section AND the candidate's reasoning includes the data-uncertainty caution AND `state.conflicts` is non-empty.
  - Env-driven fixture sets `ADVISORY_MOCK_CONFLICTS=1`, runs the normal graph entry point without seeding `state.retrieved_programs`, and asserts `final_answer` contains `## Xác minh dữ liệu`. Mock the DB cursor to raise if called, proving retrieval stayed in memory.

### End-to-end test with real ingested data — load-bearing for the thesis claim

- `tests/e2e/test_real_conflict_resolution.py` (new)
  - Marker: `@pytest.mark.requires_real_dataset` — skipped by default, run explicitly during demo prep.
  - Seeds the test database with the curated HUST + VNU-UET corpus from a one-time export at `tests/e2e/fixtures/real_dataset_dump.sql`.
  - Runs a chat conversation through `ConversationService` for one of the conflict-bearing programs.
  - Asserts: at least one resolved or unresolved outcome is present in the final session snapshot. The assistant result turn contains the verification section. The recommendation reflects either the resolved value or the uncertainty caution.
  - **Failing this test fails the phase.**

### Chat surface test — extend existing

- `tests/e2e/test_chat_web_flow.py` (extend existing)
  - Reuse the deterministic-stub fixture path. Seed a session with a conflict-bearing profile; run through the chat API; assert the polled snapshot eventually contains an `assistant_result` message with the verification section text.
  - Add a mock-retrieval variant that sets `ADVISORY_MOCK_CONFLICTS=1`, asks for the mock program/school, and asserts the chat result contains `Xác minh dữ liệu` without requiring `DATABASE_URL` or seeded Postgres data.

### What's intentionally not tested

- LLM tiebreaker output quality. Tests assert the plumbing (gateway called with the right payload, response parsed correctly, conservative `confidence="high"` threshold enforced). They do not assert that the LLM produces a "correct" rationale — that's a manual review concern during demo prep.
- Ingestion parser correctness on the real VNU-UET PDF. Dataset curation has its own acceptance check; if the curated dump validates, ingestion is considered acceptance-tested.
- Performance / scale. This phase doesn't change the performance posture.

### Test gating for "phase complete"

The phase ships only when:

1. All unit tests green.
2. All extended agent and graph integration tests green.
3. The `requires_real_dataset` end-to-end test green against the curated HUST + VNU-UET corpus.
4. A manual walkthrough of the chat UI on the real dataset produces a coherent `## Xác minh dữ liệu` section for at least one conflict-bearing program (resolved) and at least one unresolved case.

### Test running posture

- Default `pytest` (no marker): runs everything except `requires_real_dataset`. Stays fast, no DB seed required beyond what already exists.
- `ADVISORY_MOCK_CONFLICTS=1 pytest tests/e2e/test_advisory_flow.py -k mock`: runs the stable conflict-aware flow against in-memory retrieval candidates. This is the fast local demo/test path and should not require Postgres.
- `pytest -m requires_real_dataset`: runs the real-data e2e. Requires `tests/e2e/fixtures/real_dataset_dump.sql` and a reachable Postgres instance.
- The CI workflow `.github/workflows/ai-code-review.yml` is unchanged. The real-dataset test is a demo-prep / phase-completion gate, not a CI gate.
- `QUICKSTART.md` must document `pytest -m requires_real_dataset` as a phase-completion requirement.

## Rollout Order

Five sequential slices, each independently mergeable. The mock-retrieval slice comes first because it unblocks stable graph tests and demos while real dataset curation continues. Dataset curation can start in parallel with slice 3 since it has no code dependency on prior slices.

**Slice 1 — Mock retrieval mode.** Add `services/mock_retrieval.py`, the `ADVISORY_MOCK_CONFLICTS` config helper, the early guard in `services/retrieval_service.py:fetch_candidates`, `.env.example` documentation, and focused tests proving the mock path returns conflicting candidates without touching DB. This slice does not add the conflict node yet; with the current legacy retrieval flow it should already make `state.conflicts` contain a quota conflict, which is useful as a smoke test.
*Gate:* with `ADVISORY_MOCK_CONFLICTS=1`, `fetch_candidates` returns 2-3 synthetic candidates sharing one conflict key with distinct quota values, and the DB cursor is never called.

**Slice 2 — Schema fix + dataset curation (real data).** Two work items, the first of which is a hard prerequisite for the second:

1. Add `db/migrations/010_canonical_records_per_source.sql`: drop the existing `UNIQUE(school_id, admission_year, program_id, admission_method)` constraint and add `UNIQUE(school_id, admission_year, program_id, admission_method, source_url)`. Update `ingestion/storage/db_writer.py:save_canonical_records` to use the new conflict target. Without this change, the writer silently de-duplicates the conflict signal and the rest of the phase has nothing to operate on.
2. Pre-flight check on VNU-UET sources, source-registry entries, parser tuning if needed, ingestion of HUST + VNU-UET corpus, acceptance-criteria SQL check. Produces `tests/e2e/fixtures/real_dataset_dump.sql` from a one-time export.

*Gate:* at least 3 program-method tuples with distinct quota values across 2 distinct rows in `canonical_admission_records` (only possible after the migration lands).

**Slice 3 — Conflict data model + detection.** `services/conflict/models.py`, `services/conflict/detection.py`, the new fields on `AgentState` and `CandidateProgram`. Replaces the string-emission path in `retrieval_service.detect_conflicts`. Unit tests for detection only. **Does not yet wire into the graph** — `retrieval_agent` stops calling `detect_conflicts`; the conflict node doesn't exist yet, so conflicts simply aren't surfaced in this slice. Safe to merge because the policy agent's ambiguity path tolerates an empty `state.conflicts`.

**Slice 4 — Evidence + Comparison + Resolution agents.** `services/conflict/{evidence_agent,comparison_agent,resolution_agent,source_labels}.py`, the restructured prompt in `services/conflict_resolution_service.py`, and the rewritten `agents/conflict_agent.py` as the conflict-node orchestrator. Adds the `conflict` node to `graph.py` between `retrieve` and `reason`. Extends `reasoning_agent` and `explanation_agent` for `data_uncertain_fields` and the verification section. Full unit coverage for new agents; extends existing agent integration tests.
*Gate:* graph integration test in `tests/e2e/test_advisory_flow.py` passes with both resolved and unresolved fixtures, plus the env-driven mock retrieval fixture asserts `final_answer` contains `## Xác minh dữ liệu`.

**Slice 5 — Real-data end-to-end + chat surface verification + docs.** New `tests/e2e/test_real_conflict_resolution.py` with `requires_real_dataset` marker. Extends `tests/e2e/test_chat_web_flow.py` for verification-section presence. Adds the demo-prep section to `QUICKSTART.md` documenting both `ADVISORY_MOCK_CONFLICTS=1` for local mock demos and `pytest -m requires_real_dataset` as a phase-completion gate.
*Gate:* real-dataset test passes against the curated dump from slice 2, and a manual chat walkthrough produces a coherent verification section for at least one resolved and one unresolved program.

Total: 2-3 weeks if dataset curation goes smoothly. Slice 1 should be small and can land quickly; it reduces schedule risk for flow development but does not reduce the real-data acceptance bar. If slice 2's acceptance check fails on VNU-UET and a third school becomes necessary, the timeline slips — by the dataset policy, that slip is preferred over shipping synthetic data as evaluation evidence.

## Tradeoffs

### Benefits

- Operationalizes the project's central architectural claim on real data — the thesis story moves from "we designed a multi-agent conflict resolution architecture" to "we can show it resolving a real cross-source quota conflict between UET's program page and ĐHQGHN's admission proposal."
- Adds a stable mock retrieval mode that lets developers and reviewers exercise the full conflict-aware graph immediately, without waiting for DB migrations, ingestion reruns, or a fragile live dataset state.
- Deterministic-first design keeps the LLM gateway out of the load-bearing decision path. The defense answer to "how does it decide?" is a readable rule set.
- Uncertainty surfaces as a visible product property: contested data downgrades the recommendation band and tells the student to verify directly with the school.
- Reuses every existing layer — graph, inference gateway, telemetry, chat surface, ingestion pipeline. Net new code is concentrated in one new package (`services/conflict/`) plus thin extensions to two existing agents.
- All new functionality is testable on synthetic fixtures and gated on real data via the opt-in marker. The two test surfaces protect against different failure modes (logic regressions vs. dataset drift).

### Costs

- Slice 2 carries most of the schedule risk. Real-world ingestion of a school's heterogeneous sources can stall on parser quality, program-name alignment, or source availability. The bail-outs (HTML-only fallback, third-school addition, scope cut to 2 programs) preserve the "no synthetic in evaluation dataset" policy but at the cost of timeline.
- Mock mode creates a second retrieval source branch. Keep it deliberately tiny and env-gated; any attempt to make it a general fixture framework should be rejected in this phase.
- The corroboration axis in the Comparison agent introduces a non-obvious rule (mid-trust agreement can outrank a single high-trust source). This needs to be defended in the thesis writeup; the rule is justifiable in the Vietnamese admission context where proposal PDFs sometimes lag behind website updates, but it's not the only reasonable design choice. Alternative (drop corroboration, single-axis trust only) is a one-line code change if needed.
- `state.conflicts: List[str]` survives as a legacy compatibility shim. A future phase should retire it and have `policy_agent` read `state.resolution_outcomes` directly. This phase deliberately doesn't take on that refactor.
- LLM tiebreaker is conservative (only `confidence="high"` flips to resolved). The system will declare "unresolved" more often than a less-conservative threshold would. Right call for the defense story; trades demonstrability for honesty.
- Freshness scoring is out. If a reviewer asks "what about stale data?" the answer is "next phase," not "here it is." The phase scope is honest about that.

### Risks and mitigations

| Risk | Mitigation |
|---|---|
| VNU-UET pre-flight fails — sources don't conflict on quota | Add NEU or FTU as a third school. Slip timeline. |
| ĐHQGHN proposal PDF parser produces poor table extraction | Switch to HTML-only sources for VNU-UET. |
| Program-name alignment between UET site and ĐHQGHN proposal is too ambiguous | Pre-flight explicitly checks this. Swap school before parser work begins. |
| `requires_real_dataset` test passes locally but fails on demo-day Postgres | Phase-completion gate documented in `QUICKSTART.md`; demo-day environment must run it during prep. |
| Mock mode accidentally enabled in production | Default disabled, documented as local/test/demo only, and easy startup/log check: when enabled, retrieval should log or expose `metadata["mock_conflict"] = True` on returned candidates. Deployment env must not set `ADVISORY_MOCK_CONFLICTS`. |
| Mock fixture diverges from production `CandidateProgram` shape | Build mock candidates with the same Pydantic model and add tests asserting conflict-key grouping, evidence provenance, and quota dict shape. |
| LLM tiebreaker prompt produces inconsistent JSON | Conservative parser: invalid `chosen_source_url` or non-`high` confidence → `unresolved`. Failure is silent and safe. |
| Corroboration rule rejected in thesis review | Rule is documented with reasoning in the design doc and the thesis writeup. Drop-corroboration alternative is a one-line code change. |

## Decision Summary

- **Phase name:** Conflict-Aware Advisory V1
- **Scope:** Evidence/Comparison/Resolution multi-agent layer for one conflict type (quota) across 2 real Hanoi schools (HUST + VNU-UET), wired into the existing advisory graph with deterministic-first resolution and conservative LLM tiebreaker. Resolution rationale and uncertainty disclosure surface in the chat output via Vietnamese deterministic templates. An env-gated mock retrieval mode (`ADVISORY_MOCK_CONFLICTS=1`) provides stable in-memory conflict candidates for local tests and demos without touching DB. Real-data verification remains gated by opt-in pytest marker.
- **Timeline:** 2-3 weeks, contingent on slice 2 hitting the acceptance criteria on real data. Mock retrieval lands first to unblock flow work; real-data acceptance still cannot be replaced by synthetic data.
- **Reliability posture:** deterministic logic first, LLM only as tiebreaker, conservative high-confidence threshold to flip uncertainty to resolution. Unresolved cases visibly downgrade recommendation bands and tell students to verify with the school directly.
- **Explicitly deferred:** freshness scoring, other conflict types, ingestion scale-up, operator console, structured recommendation UI, retirement of the legacy `state.conflicts` shim.

This design intentionally avoids ingestion scale-up, additional conflict types, operator tooling, and UI redesign. The goal is narrower and more practical: demonstrate that the conflict resolution architecture survives contact with real Vietnamese admission data, on a tightly scoped corpus, with the resolution rationale visible to the student.
