# Thiết kế kiến trúc đích cho luận văn — Hệ thống tư vấn tuyển sinh

- **Ngày:** 2026-06-16
- **Trạng thái:** Đề xuất (chờ review)
- **Động lực:** Phục vụ luận văn tốt nghiệp (chương kiến trúc).
- **Khung kể chuyện:** "Trung thực + bảo vệ" — mô tả hệ thống đúng bản chất và *bảo vệ*
  lựa chọn thiết kế, thay vì giả lập một kiến trúc multi-agent tự chủ.
- **Phạm vi triển khai:** Spec này + một tập **cleanup code an toàn, bảo toàn hành vi**
  (C1–C4 ở §8). Các khoảng trống vận hành đưa vào mục "Hạn chế & Hướng phát triển".
- **Liên quan:** `docs/superpowers/specs/2026-06-16-architecture-audit.md` (audit gỡ nợ
  kỹ thuật cùng ngày — spec này *đồng pha*, không thay thế); `latex/OUTLINE.md`,
  `latex/FACTS.md`, `latex/CLAUDE.md` (quy tắc factual-integrity).

---

## 0. Ràng buộc nền tảng — bảo toàn năng lực hiện có

Đây là tiến hóa kiến trúc + tài liệu hóa, **không phải viết lại**. Hành vi hiện tại là
nguồn chân lý. Phải bảo toàn: mọi workflow, mọi năng lực, mọi tích hợp service, **mọi
API contract**, mọi đầu ra/side-effect, và đặc tính hiệu năng/độ tin cậy.

Ràng buộc bổ sung đặc thù luận văn:

- **Factual-integrity** (`latex/CLAUDE.md`): mọi con số/module/hành vi nêu trong luận văn
  phải truy được về code; `latex/FACTS.md` chốt giá trị đo được. Mọi đổi tên file/đổi
  cấu trúc phải **re-sync FACTS.md/OUTLINE.md**.
- **Quota Gemini free-tier** (~20 req/ngày/model/project; thêm key cùng project *không*
  tăng quota): mỗi điểm gọi LLM là tài nguyên khan hiếm — ràng buộc này *bác bỏ* việc
  nhân thêm agent.
- **Khung OUTLINE đã chốt:** `OUTLINE.md §3.3` đã *chủ động* chọn "fixed graph" thay vì
  "function-calling loop" (lý do: determinism, traceability). Spec này củng cố luận điểm
  đó, không mâu thuẫn.

---

## 1. Phát hiện cốt lõi (đính chính khung phân tích)

Brief ban đầu giả định đây là một "multi-agent system" cần tiến hóa thành "target
multi-agent architecture". Bằng chứng mã nguồn cho thấy giả định này **không đúng**:

> Hệ thống hiện tại **không phải** multi-agent theo nghĩa agent tự chủ. Nó là **một
> pipeline LangGraph tất định + một lớp điều phối định tuyến theo ý định**. Từ "agent"
> đang bị dùng cho 3 thứ khác nhau, không cái nào là agent tự ra quyết định/gọi tool động.

Bằng chứng "agent" bị overload:

| Nơi dùng "agent" | Thực chất | Bằng chứng |
|---|---|---|
| `agents/*.py` (6 file) | Node hàm LangGraph, adapter mỏng đọc/ghi `AgentState` | `graph.py:25-39` cạnh tuyến tính cố định |
| `services/conflict/*_agent.py` (3 file) | Module thuần tất định, 0 LLM | comment `resolution_agent.py:24,50` ("No LLM call") |
| `services/chat/synthesis_agent.py` | 1 call LLM ghép văn bản | `synthesis_agent.py:46` |

Toàn hệ thống chỉ có **10 điểm gọi LLM**. Một advisory run đi qua 6 node nhưng chỉ node
`profile` chắc chắn gọi LLM (và *bị bỏ qua* trong luồng chat vì `profile_seeded=True`,
`profile_agent.py:7-9`); `policy` gọi *có điều kiện* (chỉ khi có conflict); 4 node còn
lại hoàn toàn tất định.

→ **Khuyến nghị kiến trúc sư:** KHÔNG nhân bản thêm agent. Topology hiện tại phù hợp với
bài toán quy trình cố định; tính tất định là *đặc tính thiết kế có chủ đích*. Công việc
giá trị là: gỡ nợ khái niệm (chuẩn hóa thuật ngữ), xóa dead concept, sửa đảo tầng, gom
logic trùng — tất cả bảo toàn hành vi.

---

## 2. Kiểm kê năng lực (capability inventory — phải bảo toàn)

| # | Năng lực user-facing | Đường thực thi | LLM? |
|---|---|---|---|
| 1 | Phân loại ý định & định tuyến (7 route) | `intent_router.classify` | 1 (+fallback keyword) |
| 2 | Thu thập hồ sơ từng lượt (DST slot-filling) | `extractor.extract_profile_update` | ≤1 |
| 3 | Tư vấn xếp hạng ngành (advisory) | LangGraph `graph.invoke` 6 node | 0–3 (luồng chat thường chỉ `policy` có điều kiện) |
| 4 | Hỏi-đáp kiến thức (RAG) | `KnowledgeQAService.answer` | 1 embed + 1 gen / (trường,chủ đề) |
| 5 | Hybrid (so sánh + dữ liệu tư vấn) | `CompareOrchestrator` → fan-out + `synthesis_agent` | N×QA + 1 synth |
| 6 | Phát hiện & xử lý xung đột quota/điểm chuẩn | node `conflict` | 0 |
| 7 | Đánh giá điểm chuẩn / score-fit | `cutoff/assessment.assess_cutoff` | 0 |
| 8 | Policy guardrails + lọc khuyến nghị | `policy_service` (+đk `policy_inference_service`) | 0–1 |
| 9 | Sửa hồ sơ → re-rank tất định (AC7) | `_maybe_correction_rerun` | 0 |
| 10 | Phiên ẩn danh + lịch sử hội thoại | `session_service`/`repository` | 0 |
| 11 | Hàng đợi run bền (durable queue) + reaper | `run_queue_worker`, `startup.reap` | 0 |
| 12 | Debug/trace panel theo 6 stage | `@traced` + `TraceService` | 0 |

Lưu ý: "Document analysis" và "Planning" (trong ví dụ domain của brief) **không tồn tại
như năng lực chat**; phân tích tài liệu chỉ có ở *ingestion-time* (`pdf_ocr.py`,
`llm_extractor.py`).

---

## 3. Phần A — Taxonomy, định danh, lập luận bảo vệ

### A.1 Taxonomy 4 lớp (gỡ rối từ "agent")

| Lớp | Tên chuẩn | Là gì | Thành phần |
|---|---|---|---|
| 1 | **Lớp điều phối** (Orchestration / control plane) | Phân loại ý định, định tuyến, hàng đợi bền, dispatch | `intent_router`, `conversation_service`, `run_queue_worker`, dispatchers |
| 2 | **Pipeline suy luận tất định** | Graph LangGraph 6 stage, cạnh cố định | `graph.py` + 6 node `agents/` |
| 3 | **Đơn vị suy luận LLM có ràng buộc** | 10 điểm gọi LLM đơn nhiệm qua gateway | 10 prompt (xem B.3) |
| 4 | **Dịch vụ tất định** | Logic thuần, 0 LLM, kiểm thử được | retrieval, conflict, cutoff, reasoning, explanation, policy-guardrail |

### A.2 Định danh kiến trúc (tên dùng trong luận văn)

> **"Intent-Routed, Deterministic Advisory Pipeline with Bounded LLM Reasoning Units"**

Đặt trên phổ thiết kế giữa (a) một prompt monolithic và (c) bầy agent tự chủ gọi tool
động. Hệ thống ở điểm (b) **"structured/constrained agentic pipeline"**: LLM chỉ được
gọi tại điểm hẹp, có schema, có fallback; luồng điều khiển tất định.

### A.3 Lập luận bảo vệ (vì sao KHÔNG dùng multi-agent tự chủ) — củng cố OUTLINE §3.3

1. **Tính tái lập:** cùng input → cùng luồng node → cùng kết quả; 0–3 LLM call/run đều có
   fallback tất định.
2. **Khả năng truy vết:** graph cố định ↔ `advisory_trace_events` 6 stage ↔ debug panel —
   bằng chứng kiểm thử được cho hội đồng.
3. **Chi phí & quota:** Gemini free-tier khan hiếm → tối thiểu hóa LLM hop; thêm agent =
   nhân chi phí.
4. **Khả năng kiểm thử:** 4/6 stage + toàn bộ conflict/cutoff/reasoning tất định ⇒
   unit-test được.

---

## 4. Phần B — Mô hình thành phần

### B.1 Lớp 1: Điều phối

| Đơn vị | Trách nhiệm | LLM | I/O contract |
|---|---|---|---|
| **Intent Router** | Phân loại 1/7 route + subtype/topic/school | 1 (`intent_router`, flash-lite) +fallback | in `(message, profile_state, history)` → out `IntentResult{route, subtype, topic, school, needs_advisory}` |
| **Conversation Service** | Điều phối 1 lượt: extract → short-circuits tất định → router → handler → enqueue | — | in `(session_token, content)` → out `ConversationTurnResult` |
| **Queue Worker + Dispatchers** | Claim run bền (SKIP LOCKED) → execute → persist | — | in `chat_advisory_runs` row → out message + `session.status` |

7 route (`intent_router.py`): `ADVISORY_FLOW`, `KNOWLEDGE_QA`, `HYBRID`, `CLARIFICATION`,
`OUT_OF_SCOPE`, `CONVERSATIONAL` (subtype: GREETING/CAPABILITY/THANKS/GOODBYE/IDENTITY/
EMOTIONAL_SUPPORT), `RESET_PROFILE`. Short-circuits tất định *trước* router (ưu tiên):
reset → rejection → continue-advisory → correction-rerun.

### B.2 Lớp 2: Pipeline tất định (6 node, đọc/ghi `AgentState`)

| Node | Đọc | Ghi | LLM | Dịch vụ |
|---|---|---|---|---|
| `profile` | `profile_seeded`, `user_query` | `student_profile`, `retrieval_missing_data` | 1–2 *(bỏ qua khi seeded)* | `profile_inference_service` |
| `retrieve` | `student_profile`, `admission_year` | `retrieval_filters`, `retrieved_programs` | 0 | `retrieval_service` |
| `conflict` | `retrieved_programs`, `student_profile` | `conflict_records`, `resolution_outcomes`, `conflicts` | 0 | `conflict/*` |
| `reason` | `student_profile`, `retrieved_programs` | `eligibility_checks`, `ranked_recommendations` | 0 | `reasoning_service` |
| `policy` | `user_query`, …, `conflicts` | `policy_decision`, `uncertainty_reasons`, `ranked_recommendations`(lọc) | 0–1 *(chỉ khi conflict)* | `policy_service`+`policy_inference_service` |
| `explain` | hầu hết state | `final_answer`, `advisory`, `citations` | 0 | `explanation_service` |

**Khử trùng lặp có chủ đích:** node `profile` bị short-circuit trong luồng chat
(`profile_seeded=True`); DST trích delta ở tầng chat (`profile_extractor`), graph tin
tưởng snapshot.

### B.3 Lớp 3: Census 10 đơn vị LLM

| # | agent_name | Model | Out | Vòng đời | Mục đích |
|---|---|---|---|---|---|
| 1 | `intent_router` | flash-lite | json | runtime/lượt | định tuyến 7 route |
| 2 | `profile_extractor` | flash-lite | json | runtime/lượt | trích delta hồ sơ (DST) |
| 3 | `profile_agent` | flash-lite | json | khi **không** seeded | trích hồ sơ đầy đủ |
| 4 | `major_resolver` | flash-lite | json | runtime, đk (Tier-3) | gỡ nhập nhằng ngành |
| 5 | `policy_agent` | flash-lite (+fallback) | json | runtime, đk (conflict) | diễn giải policy mơ hồ |
| 6 | `knowledge_qa_agent` | **flash** (+fallback) | json | runtime /(trường,chủ đề) | trả lời RAG grounded |
| 7 | `synthesis_agent` | **flash** (+fallback) | free_text | runtime, path hybrid | ghép Khối A+B |
| 8 | `fact_extractor` | **flash** (+fallback) | json | **ingestion** | trích fact tài liệu |
| 9 | `knowledge_ocr` | flash-lite (→flash) | free_text | **ingestion** | OCR trang PDF |
| 10 | `qa_eval_judge` | flash-lite | json | **eval** | LLM-as-judge |

7 runtime + 2 ingestion + 1 eval. Mọi prompt runtime là tiếng Việt; chỉ
`POLICY_SYSTEM_PROMPT` tiếng Anh.

### B.4 Lớp 4: Dịch vụ tất định (0 LLM)

`retrieval_service` (SQL); `conflict/{detection,comparison,resolution,evidence}` (xếp
hạng `trust→corroboration→recency→confidence`); `cutoff/assessment` (score-fit +
volatility EC-15); `reasoning_service` (banding/score-fit); `explanation_service` (render
markdown); `policy_service` (guardrail); `profile/{slots,validation,major_resolver
Tier-1/2}`.

### B.5 Quy tắc sở hữu tool (Mục 3 của brief)

- **Hạ tầng dùng chung, KHÔNG thuộc đơn vị nào:** inference gateway, embedder, key-pool,
  pattern `connection_factory + _cursor`. Xếp là *cross-cutting infrastructure*.
- **Mỗi đơn vị LLM sở hữu đúng:** 1 prompt + 1 `agent_name` policy trong `registry`. Mỗi
  repository sở hữu bảng của nó.
- **Bất biến:** graph tuyến tính ⇒ không node nào gọi service của node khác; mỗi node có
  tập phụ thuộc hẹp, cố định ⇒ *không* "mọi agent gọi mọi tool".
- **Tool trùng cần gom:** conflict-key (3 module) → 1 util; `_dedupe`/vietnamese-fold →
  util chung.

### B.6 I/O schema xương sống (contract phải bảo toàn)

`AgentState` (24 field — bus pipeline) · `IntentResult` · `ConversationTurnResult`
(contract `POST /messages`: `{session_status, assistant_message, should_start_run,
profile_state, citations, run_kind, hybrid_intent, correction_note}`) · `StudentProfile`
/ `ChatProfileState` (tách `explicit_preferred_majors` vs `inferred_interest_tags`) ·
`InferenceRequest/InferenceResult` · `KnowledgeQAResult`.

---

## 5. Phần C — Topology, luồng, ranh giới, lỗi

### C.1 Sơ đồ topology

```
                          HTTP (FastAPI)  —  POST /messages  (đồng bộ, trả ACK ngay)
                                   │
                    ┌──────────────▼───────────────┐
                    │   LỚP ĐIỀU PHỐI (control)     │
                    │  ConversationService          │
                    │  1) profile_extractor (LLM)   │
                    │  2) short-circuits TẤT ĐỊNH   │  reset / rejection /
                    │     (ưu tiên trước router)    │  continue-advisory / correction-rerun
                    │  3) Intent Router (LLM, 7 route)
                    └───┬───────┬───────┬───────┬───┘
            ADVISORY    │  KNOWLEDGE_QA │ HYBRID │  CONVERSATIONAL/CLARIFY/OOS/RESET
        (async, queue)  │  (inline sync)│(async) │  (tất định, trả tĩnh)
                    │           │       │
        enqueue ────▼──┐        ▼       ▼
   chat_advisory_runs  │   KnowledgeQA   CompareOrchestrator
        (DB, bền)      │   (1 embed +    ├─ advisory graph (nếu needs_advisory)
                    │  │    1 LLM/cặp)   ├─ knowledge fan-out  ──┐ map
   ┌────────────────▼──▼─┐              └─ SynthesisAgent (LLM) ◄┘ reduce
   │ RunQueueWorker      │
   │ claim SKIP LOCKED   │──► RunDispatcher ──► graph.invoke (6 node tất định)
   │ (daemon thread)     │──► HybridDispatcher ─► CompareOrchestrator
   └─────────────────────┘            │
                                       ▼
                         advisory_trace_events (6 stage, @traced)
                                       ▲
        GET /trace ── TraceService ────┘     GET /sessions/{token} ◄── client POLLING
```

Ba mẫu hình giao tiếp (Mục 5): **Router** + **Fixed planner-executor** + **Map-reduce**.
Không supervisor động, không peer-to-peer. HITL ở dạng *ngầm* (slot-filling,
`requires_human_verification`, conflict→`uncertain`).

### C.2 Luồng giao tiếp (3 path)

- **Advisory (async):** `POST /messages` → extract + router → handler gom đủ slot →
  `should_start_run=True` → enqueue + trả ACK → worker claim → `graph.invoke` → ghi
  message + `status=completed` → client poll `GET /sessions/{token}`.
- **Knowledge-QA (sync inline):** router → `KnowledgeQAService.answer` (embed → pgvector →
  1 LLM) → trả ngay. Không qua queue.
- **Hybrid (async map-reduce):** enqueue → `CompareOrchestrator` chạy song song (ThreadPool):
  nhánh advisory graph + nhánh knowledge fan-out N cặp → `SynthesisAgent` ghép → poll.

**Contract bất biến:** `POST /messages` luôn trả ACK đồng bộ; đáp án cuối đến qua
**polling** `GET /sessions/{token}` (không SSE/WebSocket); trace qua `GET /trace`.

### C.3 Ranh giới state & memory

| Phạm vi | Nội dung | Vòng đời |
|---|---|---|
| Dài hạn (Postgres) | `chat_sessions`, `chat_messages`, `chat_advisory_runs`, `advisory_trace_events`, canonical store + knowledge chunks | bền |
| State thực thi | `AgentState` (24 field), sống trong 1 `graph.invoke` | per-run |
| Tạm thời | `history_ctx` (3 cặp), `delta`, `IntentResult` — tính lại mỗi lượt từ DB | per-turn |
| Không tồn tại (cố ý) | bộ nhớ user xuyên phiên (phiên ẩn danh) | — |

Ranh giới then chốt: (1) graph **chỉ nhận snapshot hồ sơ + câu hỏi mới**, không nhận
lịch sử hội thoại; (2) `AgentState` là điểm chia sẻ context rộng duy nhất — đánh đổi *có
chủ đích*, được *bảo vệ* chứ không sửa.

### C.4 Mô hình lỗi & quan sát (Mục 7)

Thang xuống cấp ("không bao giờ chết im lặng"): LLM lỗi → fallback model → fallback tất
định (intent→keyword, profile→rule, policy→default, knowledge→no-data,
synthesis→concatenate, major→strong[0]). Gateway: `max_retries=1` + fallback model +
key-pool xoay vòng (worst-case ~3×N HTTP). Độ bền: claim `FOR UPDATE SKIP LOCKED` +
startup reaper. Quan sát: `@traced` 6 stage qua `_safe()` (lỗi trace không hỏng run).

---

## 6. Phần D — Cleanup an toàn (C1–C4)

| # | Cleanup | Xóa mâu thuẫn | Rủi ro | FACTS re-sync |
|---|---|---|---|---|
| **C1** | `CLAUDE.md:30`: bỏ "LLM tiebreaker" → "deterministic conflict resolution" | Doc nói có LLM tiebreaker; code đã xóa hẳn | Zero (doc) | Không |
| **C2** | Đổi tên `conflict/{comparison,resolution,evidence}_agent.py` → bỏ `_agent`; cập nhật import trong `conflict_agent.py` | Module tất định mang tên "agent" | Thấp | Tên file |
| **C3** | 13 importer `agents.models → domain.models`, xóa shim `agents/models.py` | `services→agents` còn qua shim | Thấp (cơ học) | Bỏ 1 file |
| **C4** | Gom conflict-key về `services/conflict/keys.py` (quota tuple + cutoff string + text); import từ `detection`, node, `explanation_service` | Logic key ở 3 module dễ lệch | Trung bình — **phải giữ chuỗi key y hệt**; cần test | Nhẹ |

**Giữ nguyên có chủ đích:** thư mục `agents/*` (OUTLINE.md:57 gọi là *graph node*);
`synthesis_agent.py` (có LLM thật, chỉ tài liệu hóa là "bounded LLM unit").

**13 importer cần sửa (C3):** `services/mock_retrieval.py`, `services/formatting.py`,
`services/profile_inference_service.py`, `services/policy_service.py`,
`services/profile_service.py`, `services/retrieval_service.py`,
`services/cutoff/assessment.py`, `services/reasoning_service.py`,
`services/cutoff/repository.py`, `services/chat/advisory_runner.py`,
`services/conflict/detection.py`, `services/explanation_service.py`,
`services/conflict/evidence_agent.py` (→ tên mới sau C2).

---

## 7. Ánh xạ spec → chương luận văn

| Phần spec | OUTLINE.md | Dùng làm |
|---|---|---|
| §3 A.1–A.2 | §4.1.1 architecture selection | đặt tên & phân loại |
| §3 A.3 | §3.3 why fixed graph | củng cố luận điểm cốt lõi |
| §4 B.2–B.4 + §5 C.1 | §4.1.3 detailed package design | mô tả graph/agents/services |
| §4 B.3 census | §4.1.x inference gateway | bảng đơn vị LLM + model tier |
| §5 C.2–C.3 | §4.1.3 data flow | sequence + state/memory |
| §5 C.4 | §4.x retry/fallback | độ tin cậy |

---

## 8. Hạn chế & Hướng phát triển (chất liệu Limitations luận văn)

Không sửa gấp; viết thành mục Limitations:

1. **Thiếu timeout per-run** — `graph.invoke` treo sẽ chiếm worker; chỉ reaper lúc restart
   dọn. (Future: timeout + cancel.)
2. **Telemetry chỉ in-memory** — chưa đo được chi phí/độ trễ thực. (Future: persist +
   dashboard.)
3. **`ADVISORY_RUN_WORKERS=2` nhưng 1 worker** start. (Future: scale-out; queue đã sẵn
   sàng nhờ SKIP LOCKED.)
4. **Quota Gemini free-tier** — ràng buộc thực nghiệm, lý giải lựa chọn tối thiểu LLM hop.

---

## 9. Tiêu chí nghiệm thu (acceptance criteria)

1. **Bảo toàn hành vi:** bộ test hiện có **xanh y nguyên** trước/sau mọi cleanup.
2. **Bảo toàn contract:** 6 endpoint HTTP và shape phản hồi (`ConversationTurnResult`,
   `ChatSessionSnapshot`, trace payload) không đổi.
3. **C4 đặc thù:** snapshot chuỗi conflict-key (quota + cutoff) trước/sau **khớp tuyệt
   đối**; đầu ra advisory trên câu mẫu có conflict không đổi.
4. **C2/C3 đặc thù:** không còn import `agents.models` ngoài shim đã xóa; `grep
   '_agent.py'` trong `services/conflict/` trả về rỗng (trừ tên đã đổi).
5. **Tài liệu:** `CLAUDE.md` không còn nhắc "LLM tiebreaker"; `FACTS.md`/`OUTLINE.md`
   re-sync với cấu trúc file mới.
6. **Spec ↔ code khớp:** mọi claim trong spec truy được về `file:line` thực tế.

---

## 10. Ngoài phạm vi (non-goals)

- Thêm bất kỳ agent runtime/autonomous nào.
- Đổi topology (giữ Router + Fixed pipeline + Map-reduce).
- Sửa timeout/telemetry/worker (đưa vào Limitations).
- Đổi tên thư mục `agents/*` hoặc `synthesis_agent.py`.
- Soạn thảo LaTeX (có thể là pha sau, ngoài phạm vi lần này).
- Bất kỳ thay đổi nào làm đổi hành vi user-facing.
