# Thiết kế: Sprint 1 — cắt token & latency trên hot path chat

- **Ngày:** 2026-06-10
- **Trạng thái:** Draft (chờ review)
- **Phạm vi:** Inference gateway (`services/inference/`), knowledge fan-out (`services/chat/knowledge_fanout.py`), conflict tiebreak (`services/conflict/`, `agents/conflict_agent.py`)
- **Động lực gốc:** Review hiệu năng toàn hệ thống (2026-06-10) chỉ ra một số điểm lãng phí token và latency trên đường đi trực tiếp của một câu hỏi chat. Sprint 1 gom các thay đổi **đã được xác minh trực tiếp trên code**, **bảo toàn hành vi**, rủi ro thấp.

---

## 1. Bối cảnh & vấn đề

Một câu hỏi chat đi qua intent router → (advisory | knowledge | hybrid). Ba điểm lãng phí đã xác minh trên code:

1. **Output LLM không giới hạn token.** `InferenceRequest` (`services/inference/models.py:10-21`) không có field `max_tokens`, và `gemini_provider._call` (`services/inference/providers/gemini_provider.py:50-55`) không truyền `max_output_tokens`. Mọi câu trả lời (knowledge QA, synthesis, explanation, profile extraction…) có thể phình tới giới hạn output của model — tốn token đầu ra một cách không cần thiết.

2. **Fan-out kiến thức chạy tuần tự.** `run_knowledge_fanout` (`services/chat/knowledge_fanout.py:32-43`) gọi `knowledge_qa.answer()` nối tiếp cho từng cặp `(school, topic)`. Một câu hỏi hybrid 3 trường × 2 chủ đề = 6 call LLM nối đuôi, mỗi call ~2-3s ⇒ +10-15s độ trễ trong khi các call hoàn toàn độc lập.

3. **Tiebreak conflict gọi LLM mỗi conflict.** `conflict_agent` (`agents/conflict_agent.py:49-56`) lặp qua từng quota conflict; với conflict mà so sánh không quyết được, `resolve()` (`services/conflict/resolution_agent.py:52-56`) gọi tiebreak callback → một LLM call cho **mỗi** conflict indecisive. N conflict indecisive = N call LLM cùng một dạng prompt.

### Hai mục bị loại sau khi kiểm chứng (quan trọng)

Review ban đầu còn đề xuất 2 mục nữa; đọc code cho thấy **tiền đề sai**, nên **không** đưa vào spec:

- **"Gateway singleton".** Tiền đề ("dựng lại gateway mỗi call làm mất API-key cooldown / dựng lại client đắt / phân mảnh telemetry") là **sai**. Cooldown và `genai.Client` đã sống trong một singleton thread-safe cấp process (`services/inference/providers/key_pool.py:1-6, 149-159`); `InferenceTelemetry` (`services/inference/telemetry.py`) chỉ là một list **không nơi nào đọc**, nên share process-global sẽ thành memory leak. Chi phí thực của việc dựng lại gateway = một dict registry + một wrapper provider ⇒ không đáng kể.
- **"Skip extractor LLM cho bare answer".** **Đã được implement** tại `services/profile/extractor.py:109-111` (`active_slot in delta and _is_bare_answer(message) and not has_major_delta → return delta`).

## 2. Mục tiêu / Ngoài phạm vi

**Mục tiêu**
- G1. Giới hạn output token theo từng agent, **mặc định không đổi hành vi** (opt-in qua config), ngân sách đủ rộng để không cắt cụt câu trả lời thật.
- G2. Fan-out kiến thức chạy **song song**, giữ nguyên thứ tự block và semantics "mỗi call tự nuốt lỗi → sibling vẫn sống".
- G3. Gom các quota conflict indecisive thành **một** LLM call thay vì N, **không đổi** contract của `resolve()` / `resolve_cutoff_conflict()`.
- G4. Mọi LLM call vẫn đi qua `build_default_gateway()` và degrade gracefully khi `InferenceError` (đúng convention repo).
- G5. Không migration, không đổi schema, không đổi API web.

**Ngoài phạm vi**
- Gateway/registry/telemetry singleton — loại (mục 1, tiền đề sai).
- Tầng database (connection pool, index FK, bulk insert, N+1 evidence) — Sprint 2, spec riêng.
- Web/Frontend (async endpoint, delta polling, SSE, cache header) — Sprint 3, spec riêng.
- Caching kết quả intent/extraction; cắt history trong prompt intent — YAGNI ở sprint này, ghi nhận làm sau.

## 3. Quyết định kiến trúc (đã chốt qua brainstorm)

| # | Quyết định | Lý do |
|---|---|---|
| D1 | Thêm `max_tokens: Optional[int] = None` vào `InferenceRequest`; `gemini_provider._call` truyền `max_output_tokens` **chỉ khi** set | Mặc định `None` ⇒ mọi call site cũ không đổi hành vi (an toàn nhất). |
| D2 | Ngân sách token đặt trong `ModelRegistry.agent_overrides` (`services/inference/factory.py`), cùng chỗ với policy hiện có | Không rải magic number ở call site; một nơi duy nhất chỉnh, đúng pattern repo. |
| D3 | Fan-out song song bằng `ThreadPoolExecutor` (max_workers giới hạn, mặc định 4), **giữ thứ tự** kết quả theo thứ tự `(school, topic)` ban đầu | Tái dùng đúng pattern đã có ở `CompareOrchestrator`; thứ tự ổn định cho rendering/test. |
| D4 | An toàn thread dựa trên trạng thái sẵn có: `key_pool` có `threading.Lock`, repository mở connection riêng mỗi call | Không cần thêm khóa mới; đã xác minh không có shared mutable state khác trên đường fan-out. |
| D5 | Batch tiebreak theo **2 pha** trong `conflict_agent`: (1) package_evidence + compare gom `(record, report)`; (2) các report `not is_decisive` → **một** LLM call, map kết quả theo `conflict_key` | LLM chỉ chạy cho conflict indecisive (đã đúng như hiện tại); chỉ đổi từ N call → 1. |
| D6 | `resolve()` nhận **callback tra cứu** thay vì callback gọi LLM trực tiếp — chữ ký `gateway(record=, report=) -> dict` **giữ nguyên** | `resolve()` / `resolve_cutoff_conflict()` không đổi một dòng ⇒ rủi ro thấp, test cũ vẫn xanh. |
| D7 | Conflict thiếu trong response batch (malformed/partial) → coi như `{confidence: "low"}` → unresolved | Trùng đúng hành vi degrade hiện tại khi một tiebreak fail. |

## 4. Kiến trúc & thay đổi theo từng đơn vị

### Change 1 — Bounded output tokens

```
InferenceRequest  (+ max_tokens: Optional[int] = None)
   └─ gateway.run → provider.generate → _call
         └─ GenerateContentConfig(..., max_output_tokens=request.max_tokens nếu != None)
ModelRegistry.resolve(agent_name) → policy (đọc max_tokens từ agent_overrides)
```

- `InferenceRequest`: thêm field, mặc định `None`.
- `gemini_provider._call`: thêm `max_output_tokens=request.max_tokens` vào `GenerateContentConfig` chỉ khi `request.max_tokens is not None`.
- Ngân sách khởi điểm (đặt trong `agent_overrides`, tinh chỉnh sau khi đo):
  - `intent_router` ≈ 256 · `profile_extractor` ≈ 300 · `knowledge_qa_agent` ≈ 800 · `synthesis_agent` ≈ 1200 · `resolution_agent` ≈ 256.
  - `explanation_agent`: dựng cục bộ, để rộng/không set ở bước này.
- Cơ chế truyền từ policy → request: call site đọc `policy.max_tokens` (hoặc gateway gán khi build request). **Quyết định triển khai cụ thể** (gán ở call site vs gateway tự bơm) để lại cho plan — nhưng nguồn sự thật là `agent_overrides`.

### Change 2 — Parallel knowledge fan-out

```
run_knowledge_fanout(intent):
   tasks = [(school, topic) for school in schools for topic in topics]   # giữ thứ tự
   with ThreadPoolExecutor(max_workers=4):
       results = map(answer_one, tasks)        # song song, gom theo index
   blocks = [build_block(r) for r in results]  # cùng thứ tự như bản tuần tự
```

- Mỗi task = một `knowledge_qa.answer(...)` bọc try/except y như hiện tại (lỗi → `None` → no-data block). Không đổi semantics.
- Thứ tự `blocks` **bằng đúng** thứ tự bản tuần tự (gom theo index task, không theo thứ tự hoàn thành).
- Pool tạo cục bộ trong hàm (như `CompareOrchestrator`), đóng bằng context manager.

### Change 3 — Batch conflict tiebreak

```
conflict_agent:
  Pha A: for record in quota_records:
            options = package_evidence(...); report = compare(options)
            pairs.append((record, report))
  Pha B: indecisive = [(r, rep) for r, rep in pairs if not rep.is_decisive]
         decisions = batch_tiebreak(indecisive, gateway)   # 1 LLM call → {conflict_key: {...}}
  Pha C: for record, report in pairs:
            outcome = resolve(record, report, gateway=lookup(decisions))   # resolve() KHÔNG đổi
```

- Hàm mới `batch_interpret_conflict_tiebreak(pairs, gateway) -> dict[str, dict]` trong `services/conflict/resolution_inference_service.py`:
  - Gateway unavailable → `{}` (mọi indecisive thành unresolved — trùng guard hiện tại).
  - Payload = list các conflict (kèm `conflict_key`, options) trong **một** request; system prompt yêu cầu trả mảng quyết định keyed theo `conflict_key`.
  - Parse lỗi/thiếu key → key đó vắng trong dict → Pha C coi là low confidence.
- `lookup(decisions)` là callback `(record, report) -> decisions.get(record.conflict_key, {"confidence": "low"})`, khớp đúng chữ ký `GatewayFunc` ⇒ `resolve()` không đổi.
- Hàm cũ `interpret_conflict_tiebreak` (per-conflict) giữ lại hay bỏ: plan quyết (nếu không còn call site thì xóa).

## 5. Test (pytest trên `admission_test`, fakes cho gateway — đúng pattern repo)

- **Change 1:** fake provider/client bắt `GenerateContentConfig`, khẳng định `max_output_tokens` được truyền khi set và **vắng mặt** khi `max_tokens is None` (bảo toàn hành vi cũ). Một test registry: agent có override → request mang đúng ngân sách.
- **Change 2:** fake `knowledge_qa` với độ trễ nhân tạo + đếm concurrency (hoặc thời gian tổng < tổng tuần tự) để chứng minh chạy song song; test thứ tự block ổn định; test một task ném lỗi → block đó no-data, sibling còn nguyên.
- **Change 3:** fake gateway đếm **số lần** `run()` được gọi: N conflict indecisive ⇒ đúng **1** call. Test mapping `conflict_key` → đúng outcome; test response thiếu key → conflict đó unresolved; test gateway unavailable → mọi indecisive unresolved. Test hồi quy: bộ conflict decisive ⇒ **0** call LLM (như cũ).
- Chạy lại toàn bộ suite hiện có để chắc không hồi quy (đặc biệt `tests/agents/test_conflict_agent.py`).

## 6. Rủi ro & giảm thiểu

| Rủi ro | Giảm thiểu |
|---|---|
| `max_tokens` cắt cụt câu trả lời dài thật (đặc biệt synthesis/QA) | Ngân sách rộng + opt-in; đo bằng telemetry trước khi siết; explanation để rộng. |
| Fan-out song song bộc lộ non-thread-safety ẩn | Đã xác minh key_pool có lock + connection riêng mỗi call; giới hạn `max_workers`; test concurrency. |
| Batch prompt làm chất lượng tiebreak giảm so với per-conflict | Giữ nguyên tiêu chí chọn nguồn trong prompt; chỉ "high confidence" mới resolve (như cũ); fallback unresolved an toàn. |
| Tăng tải đồng thời lên Gemini (fan-out) chạm rate limit | `max_workers` nhỏ; key_pool đã có cooldown/rotation sẵn. |

## 7. Liên quan

- Review nguồn: 5 sub-agent (inference / chat-pipeline / db-rag / ingestion / web), 2026-06-10.
- Các nhóm còn lại (DB Sprint 2, Web Sprint 3) tách spec riêng khi tới lượt.
- Convention: không `git push`; không trailer AI trong commit.
