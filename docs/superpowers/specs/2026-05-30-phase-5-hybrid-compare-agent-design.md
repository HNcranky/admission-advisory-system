# Phase 5 — Hybrid Intent + CompareAgent — Design Spec

**Date:** 2026-05-30
**Status:** Approved
**Parent spec:** [`2026-05-30-intent-router-and-knowledge-qa-design.md`](./2026-05-30-intent-router-and-knowledge-qa-design.md) (Phase 5 section)

## Problem

The intent router (Phase 1) can already emit `route="HYBRID"` for questions that need *both* structured advisory data (điểm chuẩn, xác suất đậu) *and* unstructured knowledge (học phí, chương trình, học bổng) — e.g. *"So sánh UET và HUST về cả điểm chuẩn lẫn học phí"*. But today HYBRID is a placeholder: `ConversationService.handle_user_message` lumps it into `_handle_knowledge_qa`, so the structured half never runs and the user gets a single-branch answer.

Phase 5 fills the seam: a **CompareOrchestrator** that runs the advisory graph and the KnowledgeQA service **in parallel**, then a **SynthesisAgent** that merges both grounded outputs into one comparison response with sources from both, clearly separating "from structured data" vs "from the knowledge corpus" — without inventing anything.

## What already exists (Phase 5 builds on this)

| Capability | Location | Signature / detail |
|---|---|---|
| Intent routing | `services/chat/intent_router.py` | `classify(message, profile_state) -> IntentResult{route, topic, school}`; can already return `route="HYBRID"`; resolves pronouns from `preferred_schools` |
| Advisory graph (async) | `services/chat/advisory_runner.py` + `graph.py` | `run_advisory_for_session(profile_state, latest_user_message, trace_run_id) -> dict`; returns `{final_answer, advisory, citations: [Evidence], ranked_recommendations, ...}` |
| Async run dispatch | `services/chat/run_dispatcher.py` | `RunDispatcher.submit(...)` → `ThreadPoolExecutor` background run; on completion appends an `assistant_result` message + sets session status |
| KnowledgeQA (sync) | `services/knowledge/qa_service.py` | `answer(question, school, topic, conversation_context="") -> KnowledgeQAResult{has_data, answer, citations: [Citation], confidence}` — single school + single topic |
| Profile gating | `services/chat/profile_state_service.py` | `next_follow_up_question(profile)` returns the next follow-up or `None` when the profile is complete enough to run |
| Chat seam | `services/chat/conversation_service.py` | HYBRID currently falls through to `_handle_knowledge_qa` — **to be replaced by `_handle_hybrid`** |
| Run wiring | `web/routes/chat_api.py` | On `result.should_start_run` → `create_run` + `RunDispatcher().submit(...)`; frontend polls the snapshot/trace endpoint |
| Evidence model | `agents/models.py` | `Evidence{source_url, school_name, admission_year, field_name, ...}` — advisory citations |
| Citation model | `services/knowledge/models.py` | `Citation{source_url, chunk_text}` — knowledge citations |
| Inference registry | `services/inference/factory.py` | `agent_overrides` map; e.g. `knowledge_qa_agent → gemini-2.5-flash`, JSON, retry w/ flash-lite fallback |

No `CompareOrchestrator`, `SynthesisAgent`, or `HybridDispatcher` exists yet. KnowledgeQA is single-school/single-topic; multi-school comparison is handled by the orchestrator fanning out, **not** by changing Phase 4.

## Resolved design decisions

1. **Async hybrid run, mirroring the advisory model.** HYBRID with a complete profile is dispatched to the background exactly like an advisory run. The orchestrator runs both branches in parallel threads and synthesizes; `handle_user_message` returns fast with a placeholder; the frontend polls as it already does. This reuses the proven async/polling path, achieves a truthful `latency ≈ max(advisory, knowledge)`, and avoids a second (blocking) execution model. *(Rejected: synchronous in-request — blocks the HTTP request 10–30s, breaks the established UX. Rejected: KQA-sync + deferred-synthesis — splits hybrid logic across request + background and needs an interim persisted KQA result.)*

2. **Router carries multi-school/topic targets via new optional fields.** `IntentResult` gains `schools: list[str] = []`, `topics: list[...] = []`, `needs_advisory: bool = False`, leaving the existing singular `school`/`topic` (used by KNOWLEDGE_QA and Phase 4) untouched — backward compatible. The orchestrator fans KnowledgeQA out over `schools × topics`.

3. **Multi-school pure-knowledge comparisons route through HYBRID with `needs_advisory=false`.** A question like *"So sánh học phí UET và HUST"* (knowledge only, but multi-school) does not fit single-school KNOWLEDGE_QA. Rather than make Phase 4 multi-school, the router emits HYBRID + `needs_advisory=false`; the orchestrator skips the advisory branch and runs the knowledge fan-out + synthesis. All "compare / multi-school" logic lives in Phase 5.

4. **Advisory branch gates on profile completeness; the knowledge branch always runs.** When a HYBRID question arrives with an **incomplete** profile, there is **no background run**: KnowledgeQA runs inline (fast, sync) to answer the knowledge half immediately, and the response appends the next advisory follow-up question to collect the missing slot (reusing `next_follow_up_question` + `flow_state.pending_question`). Only when the profile is **complete** is the full async hybrid run dispatched. This never withholds an answer it could give, and never burns 10–30s of advisory compute against an empty profile.

5. **No auto-defer of the hybrid comparison (YAGNI).** In the incomplete-profile case we do not remember the comparison and auto-replay it once the profile completes. The knowledge half was already delivered; the advisory half emerges from the normal advisory flow on the next turn. If the user still wants the synthesized comparison, they re-ask. *(Rejected: persisting the pending hybrid question and auto-running synthesis on profile completion — extra hidden state for marginal gain.)*

6. **LLM synthesis under a strict grounding rule, with a deterministic concatenation fallback.** The SynthesisAgent makes one LLM call that may only *reorganize and compare* the two provided (already-grounded) blocks — it must never add a fact, figure, or claim absent from the input (same hard-rule philosophy as Phase 4). Output is markdown with two clearly-labelled sections plus one merged, deduped `Nguồn` list. If the synthesis LLM fails, the orchestrator falls back to deterministic concatenation (header + each available block verbatim + merged sources) so the chat never breaks. *(Rejected: pure deterministic concatenation — two pasted blocks, not a real "so sánh tổng hợp".)*

## Architecture

### End-to-end flow

```
handle_user_message(session_token, content)
│
├── intent = IntentRouter.classify(content, profile_state)   # extended for HYBRID
│
└── route == HYBRID → _handle_hybrid(...)
    │
    ├── profile INCOMPLETE  (next_follow_up_question(profile) != None)
    │     → KnowledgeQA inline, multi-school fan-out (sync, <5s)
    │     → response = knowledge answer + "\n\nNhân tiện, <follow-up>"
    │     → flow_state = {active_flow: "ADVISORY_FLOW", pending_question: <follow-up>}
    │     → ConversationTurnResult(should_start_run=False)        # NO background run
    │
    └── profile COMPLETE
          → placeholder = "Câu hỏi này cần đối chiếu cả dữ liệu tuyển sinh lẫn
                            thông tin trường, mình đang tổng hợp..."
          → ConversationTurnResult(should_start_run=True, run_kind="hybrid")
          → web route → HybridDispatcher.submit(intent, profile_state, content)
                background (HybridDispatcher._execute):
                  CompareOrchestrator.run(intent, profile_state, content):
                    ├─ thread A: advisory_runner(profile_state, content)   # if needs_advisory
                    ├─ thread B: knowledge fan-out (schools × topics)
                    └─ SynthesisAgent.synthesize(advisory, knowledge, content)
                  → append assistant_result message, set status "completed"
          → frontend polls snapshot → synthesized comparison answer
```

The advisory graph (`graph.invoke()`) is **unchanged** — invoked through the existing `run_advisory_for_session`, exactly as the advisory-only path does today.

### Components

| Component | File | Change |
|---|---|---|
| **IntentRouter** | `services/chat/intent_router.py` | Add `schools`, `topics`, `needs_advisory` to `IntentResult`; extend the system prompt + examples to emit them for HYBRID. Singular `school`/`topic` unchanged. |
| **CompareOrchestrator** | `services/chat/compare_orchestrator.py` *(new)* | Runs both branches in parallel (`ThreadPoolExecutor`), calls `SynthesisAgent`. Pure logic, no DB. Deps injected (`advisory_runner`, `knowledge_qa`, `synthesis_agent`) for tests. |
| **SynthesisAgent** | `services/chat/synthesis_agent.py` *(new)* | One grounding-strict LLM call → markdown 2 sections + merged sources; deterministic concatenation fallback. |
| **HybridDispatcher** | `services/chat/run_dispatcher.py` (extend) or sibling class | Submits the hybrid run to the background, calls the orchestrator, persists the assistant message + session status (mirrors `RunDispatcher`). |
| **ConversationService** | `services/chat/conversation_service.py` | Real `_handle_hybrid()` replacing the borrowed `_handle_knowledge_qa` branch; profile gate. |
| **chat_api route** | `web/routes/chat_api.py` | When `should_start_run` + `run_kind=="hybrid"` → dispatch via `HybridDispatcher` instead of `RunDispatcher`. |
| **ConversationTurnResult** | `services/chat/models.py` | Gains `run_kind: str = "advisory"` so the route can pick the right dispatcher; defaults keep the advisory path unchanged. |
| **Inference registry** | `services/inference/factory.py` | Register `synthesis_agent` (gemini-2.5-flash, free_text/markdown or JSON, temp 0.0, retry w/ flash-lite fallback). |

### IntentResult (extended)

```python
class IntentResult(BaseModel):
    route: Literal["ADVISORY_FLOW", "KNOWLEDGE_QA", "HYBRID", "CLARIFICATION", "OUT_OF_SCOPE"]
    topic: Optional[Literal[...]] = None     # kept — KNOWLEDGE_QA
    school: Optional[str] = None             # kept — KNOWLEDGE_QA
    # new, HYBRID-only (default empty → no behavior change for other routes):
    schools: list[str] = []                  # e.g. ["VNU-UET", "HUST"]
    topics: list[Literal[...]] = []          # e.g. ["tuition", "curriculum"]
    needs_advisory: bool = False             # router confirms the advisory branch is actually needed
```

Router prompt additions: for HYBRID, emit `schools`/`topics` resolved from the message (and pronouns from `preferred_schools`/`preferred_majors`); set `needs_advisory=true` only when the question genuinely needs điểm chuẩn / xác suất đậu, `false` for multi-school pure-knowledge comparisons.

### CompareOrchestrator

```python
class CompareOrchestrator:
    def __init__(self, advisory_runner=None, knowledge_qa=None, synthesis_agent=None):
        self.advisory_runner = advisory_runner or run_advisory_for_session
        self.knowledge_qa     = knowledge_qa or KnowledgeQAService()
        self.synthesis_agent  = synthesis_agent or SynthesisAgent()

    def run(self, intent, profile_state, content, trace_run_id=None) -> str:
        with ThreadPoolExecutor(max_workers=2) as ex:
            adv_future = (
                ex.submit(self._run_advisory, profile_state, content, trace_run_id)
                if intent.needs_advisory else None
            )
            kqa_future = ex.submit(self._run_knowledge, intent, profile_state, content)
            advisory  = self._safe(adv_future)   # each branch swallows its own error
            knowledge = self._safe(kqa_future)
        return self.synthesis_agent.synthesize(advisory, knowledge, content)
```

- **`_run_advisory`** → `run_advisory_for_session(...)`; extract `final_answer` (or `advisory`) + `citations` (Evidence). Empty/throw → treated as "advisory missing".
- **`_run_knowledge`** → fan-out: `for school in (intent.schools or [intent.school]): for topic in (intent.topics or [intent.topic]):` call `knowledge_qa.answer(...)`; label each `KnowledgeQAResult` with `(school, topic)`. A single call throwing → that pair is `has_data=False`; others continue.
- **Latency** = `max(advisory, knowledge fan-out) + synthesis` — satisfies "≈ max, not sum".
- **`needs_advisory=false`** → no advisory thread; knowledge fan-out + synthesis only.

### SynthesisAgent

```python
class SynthesisAgent:
    def synthesize(self, advisory, knowledge, question) -> str:
        # advisory: {answer: str|None, citations: [Evidence]} | None
        # knowledge: [{school, topic, result: KnowledgeQAResult}]
        try:
            return self._llm_synthesize(advisory, knowledge, question)   # grounded LLM call
        except Exception:
            return self._concatenate(advisory, knowledge)               # deterministic fallback
```

Grounding system prompt (Vietnamese), hard rule: *only reorganize and compare the provided blocks; never add a figure or fact not present in the input; if a part is missing, state it plainly.* Output: markdown with **two labelled sections** ("Theo dữ liệu tuyển sinh" / "Thông tin trường") and a comparison table where sensible, followed by one merged **Nguồn** list.

### Merged citations

`Evidence.source_url` (advisory) ∪ `Citation.source_url` (knowledge), deduped by URL → a single trailing **Nguồn** block, labelled by branch where useful.

## Error handling

Principle: **each branch swallows its own error inside the executor** — no branch can crash the other; synthesis always receives a real result or a "missing data" signal from each side.

| Situation | Behavior |
|---|---|
| Advisory ok, knowledge **no data** (all `has_data=False`) | Synthesis: full advisory section + knowledge section states *"Hệ thống chưa có dữ liệu về [topic] của [trường]"* |
| Knowledge ok, advisory **empty/throws** (`final_answer` empty or graph raises) | Synthesis: full knowledge section + advisory section states the missing part |
| **Both** missing | One polite combined "chưa đủ dữ liệu cả hai phần..." message — nothing fabricated |
| **SynthesisAgent LLM fails** | Deterministic concatenation: header + each available block verbatim + merged sources |
| One KQA call in the fan-out throws | That `(school, topic)` → `has_data=False`; the other pairs still run |
| `HybridDispatcher._execute` throws unexpectedly | Same as `RunDispatcher` today: append a polite error message + `status="failed"`, re-raise for logging |
| Router returns HYBRID but `schools`/`topics` empty | Fan-out falls back to singular `intent.school`/`intent.topic`; if both null → knowledge "no data" path |

Acceptance criterion *"Một nhánh thiếu data → nhánh đó fallback, nhánh kia vẫn trả lời, response ghi rõ phần thiếu"* is served directly by the table above.

## Testing strategy

**`tests/services/chat/test_compare_orchestrator.py`** *(new — fake `advisory_runner` / `FakeKnowledgeQA` / `FakeSynthesis`):*
- Both branches have data → synthesis receives both blocks, called exactly once.
- `needs_advisory=false` → `advisory_runner` **not** called (assert), knowledge only.
- Knowledge no-data → synthesis receives the missing flag, advisory still full.
- Advisory throws → orchestrator does not break; synthesis receives `advisory=None`.
- Fan-out: `schools=["UET","HUST"]`, `topics=["tuition"]` → KQA called twice with correct labels.
- Latency: fake per-branch delays → assert wall-clock ≈ max, not sum.

**`tests/services/chat/test_synthesis_agent.py`** *(new):*
- Two full blocks → output has two distinct sections + merged deduped `Nguồn`.
- LLM throws → deterministic concatenation still yields both blocks.
- Grounding: assert the prompt carries the "no facts beyond input" hard rule.

**`tests/services/chat/test_conversation_service.py`** *(extend — `FakeIntentRouter` returning `route=HYBRID`):*
- HYBRID + profile **complete** → `should_start_run=True`, `run_kind="hybrid"`, no inline answer.
- HYBRID + profile **incomplete** → knowledge inline + follow-up, `should_start_run=False`, `pending_question` persisted.
- Profile state **not reset** after a HYBRID turn.

**`tests/services/chat/test_intent_router.py`** *(extend):*
- Compare điểm chuẩn + học phí → `route=HYBRID`, `needs_advisory=true`, `schools`/`topics` populated.
- Pure advisory question → **not** HYBRID (still `ADVISORY_FLOW`).
- Compare học phí of two schools (pure knowledge) → HYBRID + `needs_advisory=false`.

**`tests/services/chat/test_hybrid_integration.py`** *(new — acceptance):*
- Full data both branches / one branch missing / both missing — assert the response separates the two parts.
- Assert the response distinguishes structured-data content from knowledge-corpus content.

## Acceptance Criteria (from parent spec)

- [ ] Comparison question across điểm chuẩn + học phí → `route=HYBRID`, both branches called
- [ ] Pure advisory question does **not** trigger HYBRID → stays `ADVISORY_FLOW`
- [ ] Response clearly separates the structured-data part from the knowledge-corpus part
- [ ] One branch missing data → that branch falls back, the other answers normally, the response states what is missing
- [ ] Total latency ≈ `max(latency_advisory, latency_knowledge_qa)`, not the sum
- [ ] Integration test: full data both branches / one branch missing / both missing

## Out of scope (named, to keep focus)

- Auto-defer of the hybrid comparison after the profile completes (decision 5 — YAGNI)
- Tracing/telemetry parity for the hybrid path (deferred, as in Phase 4)
- Native multi-school KnowledgeQA — the orchestrator fan-out replaces it
- Streaming per-branch results — the frontend keeps polling

## Not changed

- Advisory graph (`profile → retrieve → conflict → reason → policy → explain`)
- Structured admission schema and ingestion pipeline
- `KnowledgeQAService` internals (Phase 4) — single-school `answer()` unchanged
- Intent router behavior for non-HYBRID routes and `FlowState` semantics (Phase 1)
- The existing async/polling UX for advisory-only runs
