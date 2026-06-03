# Intent Router & Knowledge QA — Design Spec

**Date:** 2026-05-30  
**Status:** Approved

## Problem

Hệ thống hiện tại chỉ có một luồng xử lý tuyến tính (`profile → retrieve → conflict → reason → policy → explain`). Khi user hỏi các câu bên lề như "học phí trường này bao nhiêu?" hay "chương trình học gồm gì?", hệ thống vẫn ép câu hỏi vào luồng tư vấn tuyển sinh và trả lời sai mục đích.

Nguyên nhân: không có bước phân loại intent, không có nhánh xử lý riêng cho câu hỏi knowledge/unstructured.

## Target Architecture

```
User
 ↓
IntentRouter
 ├── ADVISORY_FLOW    → advisory graph (giữ nguyên)
 ├── KNOWLEDGE_QA     → KnowledgeQAService (RAG)
 ├── HYBRID           → CompareOrchestrator (cả 2 nhánh song song)
 ├── CLARIFICATION    → focused follow-up question
 └── OUT_OF_SCOPE     → thông báo ngoài phạm vi
```

## Intent Schema

```python
AdmissionIntent = Literal[
    "ADVISORY_FLOW",
    "KNOWLEDGE_QA",
    "HYBRID",
    "CLARIFICATION",
    "OUT_OF_SCOPE",
]

KnowledgeTopic = Literal[
    "tuition",
    "curriculum",
    "scholarship",
    "dormitory",
    "career",
    "admission_policy",
    "program_overview",
]
```

Router output (JSON):
```json
{
  "route": "KNOWLEDGE_QA",
  "topic": "tuition",
  "school": "VNU-UET",
  "return_to_flow": true
}
```

---

## Phase 1 — Intent Router + Flow State Preservation

**Mục đích:** Ngăn hệ thống ép câu hỏi bên lề vào luồng tư vấn. User nhận được hành vi đúng ngay lập tức dù chưa có data RAG.

**Thay đổi:**
- Thêm `IntentRouter` (LLM call riêng) làm bước đầu tiên trong `ConversationService`
- Với `KNOWLEDGE_QA` chưa có data: trả fallback rõ ràng + nhắc user quay lại luồng
- Session giữ `active_flow` và `return_to_flow` để không mất profile state khi rẽ nhánh

### 1.1 Luồng xử lý

```
handle_user_message(session_token, content)
│
├── 1. save_message(content)
├── 2. profile_state = get_profile_state()       # đã có sẵn
│   flow_state    = get_flow_state()             # column mới
│
├── 3. intent = IntentRouter.classify(content, profile_state)
│             └── LLM call riêng, JSON output, ~200ms
│
├── 4a. route == ADVISORY_FLOW
│       → profile extraction → merge → check missing_slots
│       → update flow_state.pending_question nếu có follow-up
│       → IF profile đủ: should_start_run=True
│
├── 4b. route == KNOWLEDGE_QA
│       → update flow_state { return_to_flow=True }
│       → return fallback message
│       → IF return_to_flow AND missing_slots: append pending_question
│
├── 4c. route == OUT_OF_SCOPE
│       → return polite decline
│       → IF return_to_flow AND missing_slots: append pending_question
│
└── 4d. route == CLARIFICATION (+ HYBRID fallback)
        → return generic clarification request
        → IF return_to_flow AND missing_slots: append pending_question
```

Advisory graph (`graph.invoke()`) **không thay đổi** — chỉ được gọi khi `ADVISORY_FLOW` + profile đủ, y hệt trước đây.

### 1.2 IntentRouter Service

**File:** `services/chat/intent_router.py`

**Output schema:**

```python
class IntentResult(BaseModel):
    route: Literal["ADVISORY_FLOW", "KNOWLEDGE_QA", "HYBRID", "CLARIFICATION", "OUT_OF_SCOPE"]
    topic: Optional[Literal[
        "tuition", "curriculum", "scholarship",
        "dormitory", "career", "admission_policy", "program_overview"
    ]] = None
    school: Optional[str] = None   # resolved từ message hoặc profile_state.preferred_schools
    return_to_flow: bool = False    # True nếu profile_state có bất kỳ dữ liệu nào
```

**LLM call:** structured JSON output, follow pattern của `profile_inference_service.py`.

**System prompt (tóm tắt):**
- Giải thích 5 route và khi nào dùng mỗi route
- Nếu message dùng đại từ ("trường này", "ở đó"), resolve từ `preferred_schools` / `preferred_majors` trong profile được truyền vào
- Trả JSON thuần, không giải thích

**User turn:**
```
Tin nhắn: "{message}"
Trường quan tâm: {preferred_schools or "chưa có"}
Ngành quan tâm:  {preferred_majors or "chưa có"}
Đã có thông tin: {non-null profile fields}
```

**Error fallback:** LLM throw hoặc parse fail → trả `IntentResult(route="ADVISORY_FLOW")`. Không propagate exception.

**`HYBRID` trong Phase 1:** Router có thể trả về HYBRID nhưng `ConversationService` fallback về `_handle_advisory()` (Phase 5 mới implement đầy đủ).

### 1.3 FlowState Model + DB Migration

**Model mới** trong `services/chat/models.py`:

```python
class FlowState(BaseModel):
    active_flow:      Optional[str] = None   # "ADVISORY_FLOW" khi đang trong luồng
    return_to_flow:   bool = False           # có advisory flow đang dở không
    pending_question: Optional[str] = None  # follow-up question cuối cùng đã hỏi user
```

**Migration** — `db/migrations/012_flow_state.sql`:

```sql
ALTER TABLE chat_sessions
    ADD COLUMN IF NOT EXISTS flow_state_json JSONB NOT NULL DEFAULT '{}';
```

**Repository additions** trong `services/chat/repository.py`:

```python
def get_flow_state(self, session_token: str) -> FlowState: ...
def update_flow_state(self, session_token: str, flow_state: FlowState) -> None: ...
```

**Lifecycle của FlowState:**

| Sự kiện | Thay đổi |
|---|---|
| ADVISORY turn, trả follow-up question | `active_flow="ADVISORY_FLOW"`, `pending_question=<question>` |
| ADVISORY turn, profile đủ (run bắt đầu) | `active_flow="ADVISORY_FLOW"`, `return_to_flow=False`, `pending_question=None` |
| KNOWLEDGE_QA hoặc OUT_OF_SCOPE turn | `return_to_flow=True` nếu `active_flow` đã set; giữ nguyên `pending_question` |
| Session mới | `{}` — default |

### 1.4 ConversationService Changes

`handle_user_message()` tách thành private methods để giữ readable:

```python
class ConversationService:
    def __init__(self, repository=None, extract_profile=None, intent_router=None):
        self.intent_router = intent_router or IntentRouter()  # injectable để test

    def handle_user_message(self, session_token, content) -> ConversationTurnResult:
        self.repository.append_message(...)
        profile_state = self.repository.get_profile_state(session_token)
        flow_state    = self.repository.get_flow_state(session_token)
        intent        = self.intent_router.classify(content, profile_state)

        if intent.route == "ADVISORY_FLOW":
            return self._handle_advisory(session_token, content, profile_state, flow_state)
        elif intent.route == "KNOWLEDGE_QA":
            return self._handle_knowledge_qa(session_token, intent, flow_state)
        elif intent.route == "OUT_OF_SCOPE":
            return self._handle_out_of_scope(session_token, flow_state)
        else:  # CLARIFICATION + HYBRID fallback
            return self._handle_clarification(session_token, flow_state)

    def _handle_advisory(self, ...):
        # Logic hiện tại giữ nguyên
        # Thêm: update flow_state.pending_question khi trả follow-up question
        # Thêm: clear flow_state khi profile đủ

    def _handle_knowledge_qa(self, session_token, intent, flow_state):
        # TOPIC_LABELS: dict map topic key → tiếng Việt, e.g. {"tuition": "học phí", "curriculum": "chương trình học", ...}
        topic_label  = TOPIC_LABELS.get(intent.topic, intent.topic or "thông tin này")
        school_label = intent.school or "trường bạn hỏi"
        fallback = (
            f"Hệ thống chưa có dữ liệu về {topic_label} của {school_label}. "
            f"Bạn có thể liên hệ trực tiếp nhà trường để biết thêm chi tiết."
        )
        response = self._append_return_prompt(fallback, flow_state)
        if flow_state.active_flow == "ADVISORY_FLOW":
            self.repository.update_flow_state(
                session_token,
                flow_state.model_copy(update={"return_to_flow": True})
            )
        ...

    def _append_return_prompt(self, message: str, flow_state: FlowState) -> str:
        if flow_state.return_to_flow and flow_state.pending_question:
            return f"{message}\n\nNhân tiện, {flow_state.pending_question}"
        return message
```

### 1.5 Error Handling

| Tình huống | Hành vi |
|---|---|
| IntentRouter LLM throw hoặc parse fail | Fallback `IntentResult(route="ADVISORY_FLOW")` — không break gì |
| `route="HYBRID"` (chưa implement) | Fallback `_handle_advisory()` |
| `school=null` trong KNOWLEDGE_QA | Label *"trường bạn hỏi"* trong fallback message |
| `topic=null` trong KNOWLEDGE_QA | Label *"thông tin này"* trong fallback message |
| `get_flow_state()` / `update_flow_state()` DB lỗi | Propagate — không swallow storage failures |

### 1.6 Testing Strategy

**`tests/services/chat/test_intent_router.py`** — unit tests với mock LLM:
- ≥ 20 cases bao phủ 5 routes
- ADVISORY: *"25 điểm A00 nên chọn trường nào"*, *"em có đậu NEU không"*, *"tư vấn ngành CNTT"*, ...
- KNOWLEDGE_QA: *"học phí UET bao nhiêu"*, *"chương trình học gồm gì"*, *"có học bổng không"*, ...
- OUT_OF_SCOPE: *"thời tiết hôm nay"*, *"kể chuyện cười"*, ...
- CLARIFICATION: *"thế còn cái đó thì sao"* (không có profile context), ...
- Pronoun resolution: *"trường này học phí bao nhiêu"* + `preferred_schools=["VNU-UET"]` → `school="VNU-UET"`
- LLM fail → fallback ADVISORY_FLOW

**`tests/services/chat/test_conversation_service.py`** — mở rộng file hiện có với `FakeIntentRouter`:
- Mỗi route → đúng branch được gọi
- `_append_return_prompt`: `return_to_flow=True` + `pending_question` → câu nhắc xuất hiện cuối response
- Profile state **không bị reset** sau KNOWLEDGE_QA turn
- `flow_state.pending_question` được lưu khi ADVISORY follow-up, giữ nguyên khi rẽ KNOWLEDGE_QA

**`tests/services/chat/test_repository.py`** — mở rộng:
- `get_flow_state()` trả `FlowState()` default khi column rỗng (`{}`)
- `update_flow_state()` round-trip đúng

**Acceptance criteria tests** — 6 case trong spec map 1:1 vào test cases.

**Acceptance Criteria:**
- [ ] `"học phí UET bao nhiêu?"` → route `KNOWLEDGE_QA`, KHÔNG chạy advisory graph
- [ ] `"Em 25 điểm A00 nên chọn ngành gì?"` → route `ADVISORY_FLOW`, flow hiện tại không thay đổi
- [ ] `"thời tiết hôm nay thế nào?"` → route `OUT_OF_SCOPE`, trả lời lịch sự
- [ ] `KNOWLEDGE_QA` chưa có data → *"Hệ thống chưa có dữ liệu về [topic] của [trường], bạn có thể liên hệ trực tiếp nhà trường..."*
- [ ] Sau trả lời câu bên lề, `return_to_flow = true` → agent nhắc lại câu hỏi trước đó trong luồng tư vấn
- [ ] Profile state của user KHÔNG bị reset khi route sang nhánh khác
- [ ] Unit test router với ≥ 20 test cases bao phủ 5 intent types

---

## Phase 2 — Corpus Infrastructure

> **Thiết kế chi tiết:** [`2026-05-30-phase-2-corpus-infrastructure-design.md`](./2026-05-30-phase-2-corpus-infrastructure-design.md). Phần dưới chỉ là tóm tắt.

**Mục đích:** Dựng nền tảng lưu trữ tài liệu unstructured (vector store) để Phase 3 ingest vào và Phase 4 query được.

**Tóm tắt quyết định:**
- Vector store: **pgvector** trên image `pgvector/pgvector:pg16` (thay `postgres:16-alpine`).
- Embedding: **`gemini-embedding-001` @ 768 dims**, cosine, vector L2-normalized; hằng số `EMBEDDING_DIM = 768`.
- Hai bảng mới **`knowledge_documents`** + **`knowledge_chunks`** (tránh va chạm `raw_documents` của admission).
- Index `(school, topic)` + HNSW `vector_cosine_ops`; idempotency key `UNIQUE (source_url, span_start, span_end)`.
- `KnowledgeChunkRepository` (`services/knowledge/`): `upsert_chunk`, `search_by_metadata`, `vector_search`.

**Acceptance Criteria:** xem spec chi tiết.

---

## Phase 3 — Data Collection

**Mục đích:** Crawl và ingest tài liệu unstructured từ các nguồn trường vào corpus.

**Cấu trúc mới trong `ingestion/`:**

```
ingestion/
  knowledge/
    registry/     — danh sách URL theo trường + document_type
    fetchers/     — download HTML/PDF
    parsers/      — extract text
    chunkers/     — sliding window 512 tokens, overlap 64
    embedders/    — tạo embedding
    pipeline.py   — orchestrate
```

Registry entry mẫu:
```json
{
  "school": "VNU-UET",
  "sources": [
    { "url": "...", "document_type": "tuition_page", "topic": "tuition" },
    { "url": "...", "document_type": "curriculum_pdf", "topic": "curriculum" }
  ]
}
```

**Acceptance Criteria:**
- [ ] ≥ 3 trường (HUST, NEU, VNU-UET) có registry entry với ≥ 2 `document_type` mỗi trường
- [ ] Pipeline chạy end-to-end: fetch → parse → chunk → embed → upsert
- [ ] Re-run là idempotent (không tạo duplicate cho cùng `source_url + span`)
- [ ] PDF parser xử lý được file nhiều trang, giữ metadata trang trong `span`
- [ ] Script verify sau ingest: đếm chunks per school/topic, flag trường thiếu data
- [ ] Không ảnh hưởng đến admission ingestion pipeline hiện tại

---

## Phase 4 — KnowledgeQA RAG Agent

**Mục đích:** Trả lời câu hỏi bên lề từ corpus, có trích dẫn nguồn, không bịa nếu không có bằng chứng.

**Pipeline:**

```
question + { school, topic }
  ↓ metadata filter (school + topic)
  ↓ vector search
  ↓ rerank
  ↓ generate với citations
  ↓ nếu top score < threshold (default 0.5, configurable) → fallback "chưa có dữ liệu"
```

`KnowledgeQAService` interface:
```python
def answer(question: str, school: str, topic: str, conversation_context: str) -> KnowledgeQAResult:
    # returns { answer, citations: [{source_url, chunk_text}], confidence }
```

System prompt hard rule:
> Chỉ trả lời dựa trên các đoạn văn bản được cung cấp. Nếu không đủ bằng chứng, nói rõ: "Hệ thống chưa có dữ liệu về [topic] của [school]." Không suy diễn hoặc bổ sung thông tin ngoài context.

**Acceptance Criteria:**
- [ ] `"Học phí VNU-UET bao nhiêu?"` → trả lời có số liệu kèm `source_url` (nếu data đã ingest)
- [ ] Topic chưa có data → fallback message rõ ràng, KHÔNG có số liệu bịa
- [ ] `citations` chứa `source_url` và `chunk_text` tương ứng
- [ ] Confidence < threshold (default 0.5) → tự động fallback, không generate
- [ ] `school` được resolve từ conversation context khi user nói "trường này"
- [ ] Integration test: mock corpus → query → assert answer grounded trong corpus
- [ ] Response time KnowledgeQA pipeline < 5s (p95) trong môi trường test

---

## Phase 5 — Hybrid Intent + CompareAgent

**Mục đích:** Xử lý câu hỏi cần cả structured advisory data lẫn unstructured knowledge, trả về so sánh tổng hợp.

**Pipeline:**

```
HYBRID route
  ↓
CompareOrchestrator
  ├── [song song] AdvisoryGraph (structured)
  ├── [song song] KnowledgeQAService (unstructured)
  └── SynthesisAgent → response có cấu trúc + citations cả 2 nguồn
```

Router extract cho HYBRID:
```json
{
  "route": "HYBRID",
  "schools": ["VNU-UET", "NEU"],
  "topics": ["tuition", "curriculum"],
  "needs_advisory": true
}
```

**Acceptance Criteria:**
- [ ] Câu hỏi so sánh 2 trường xét cả điểm chuẩn lẫn học phí → route `HYBRID`, gọi cả 2 nhánh
- [ ] Câu hỏi thuần advisory KHÔNG trigger `HYBRID` → vẫn là `ADVISORY_FLOW`
- [ ] Response phân biệt rõ phần từ structured data và phần từ knowledge corpus
- [ ] Một nhánh thiếu data → nhánh đó fallback, nhánh kia vẫn trả lời bình thường, response ghi rõ phần thiếu
- [ ] Total latency ≈ max(latency_advisory, latency_knowledge_qa), không phải tổng cộng
- [ ] Integration test: full data cả 2 nhánh / thiếu data 1 nhánh / thiếu data cả 2

---

## Dependencies giữa các phase

```
Phase 1 (router)  ──────────────────────────────→ có thể deploy độc lập
Phase 2 (corpus schema) ──┐
Phase 3 (data collection) ┤  Phase 2 phải xong trước Phase 3
Phase 4 (RAG agent) ──────┘  Phase 3 phải xong trước Phase 4 (cần data)
Phase 5 (hybrid) ─────────── Phase 1 + Phase 4 phải xong trước Phase 5
```

## Không thay đổi

- Advisory graph hiện tại (`profile → retrieve → conflict → reason → policy → explain`) giữ nguyên hoàn toàn
- Structured admission data schema không thay đổi
- Ingestion pipeline admission hiện tại không thay đổi
