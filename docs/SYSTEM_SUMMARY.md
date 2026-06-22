# Tổng quan hệ thống — Admission Advisory System

> Tài liệu tóm tắt toàn hệ thống: kiến trúc, các luồng backend, luồng dữ liệu,
> **các kỹ thuật áp dụng và hiệu quả đo được**. Cập nhật: **2026-06-20**
> (số liệu đo trên branch `refactor/codebase`; nguồn số liệu: `latex/FACTS.md`
> đo 2026-06-19, báo cáo eval 2026-06-10, census corpus 2026-06-20).

Hệ thống là một **trợ lý tư vấn tuyển sinh đại học Việt Nam có nhận biết mâu
thuẫn dữ liệu (conflict-aware)**. Nó crawl các nguồn chính thống (trang tuyển
sinh, đề án PDF, văn bản Bộ GD&ĐT, API curriculum), chuẩn hóa về một kho dữ liệu
canonical trên Postgres, rồi phục vụ một chat UI: thu thập hồ sơ học sinh qua hội
thoại, gợi ý ngành/trường phù hợp, trả lời câu hỏi kiến thức (học phí, học bổng,
KTX…) bằng RAG, và luôn nói rõ khi các nguồn dữ liệu mâu thuẫn nhau.

Phạm vi dữ liệu hiện tại:
- **Dữ liệu tuyển sinh có cấu trúc** (chỉ tiêu/phương thức/điểm chuẩn): **HUST,
  VNU-UET** (2 trường có registry ingestion).
- **Kho kiến thức RAG**: **HUST, NEU, VNU-UET, MOET**.

Quy mô mã nguồn (FACTS.md, 2026-06-19): **34.413 dòng Python** (16.844 dòng
production, còn lại là test), 414 file `.py`, 371 commit trên branch, **1.123
test** (1.122 pass / 1 skip).

---

## 1. Kiến trúc tổng thể

Hệ thống gồm **4 khối lớn**, tách bạch giữa phần chạy offline (ingestion) và
phần phục vụ online (serving):

```
┌─────────────────────────┐      ┌──────────────────────────────┐
│  INGESTION (offline,CLI)│      │   SERVING (online, FastAPI)  │
│                         │      │                              │
│  ① Structured pipeline  │      │  ④ Web UI (Jinja2 + JS)      │
│     quota/phương thức/  │      │       │ HTTP + polling       │
│     điểm chuẩn          │      │  ⑤ Chat services (turn_graph)│
│  ② Knowledge pipeline   │      │     session / intent /       │
│     PDF, web, API → RAG │      │     slot-filling / dispatch  │
└───────────┬─────────────┘      │       │                      │
            │ ghi                │  ⑥ Advisory pipeline         │
            ▼                    │     (LangGraph 6 node)       │
┌─────────────────────────┐      │  ⑦ Knowledge QA (qa_graph)   │
│  ③ Postgres 16 +        │◄─────┤       │                      │
│     pgvector (Docker)   │ đọc  │  ⑧ Inference Gateway         │
│  canonical store,       │      │     (mọi LLM call → Gemini)  │
│  knowledge chunks,      │      └───────────────┬──────────────┘
│  chat, cache, queue     │                      │ spans
└─────────────────────────┘      ┌───────────────▼──────────────┐
                                  │  ⑨ Langfuse (observability    │
                                  │     sink duy nhất, self-host) │
                                  └──────────────────────────────┘
```

- **Ingestion** chạy thủ công bằng CLI (`python -m ingestion.main`,
  `ingestion.knowledge.pipeline`…), không chạy theo lịch. Kết quả là dữ liệu
  trong Postgres — serving không bao giờ tự crawl.
- **Postgres + pgvector** là điểm gặp nhau duy nhất giữa hai phía: ingestion
  ghi vào, serving chủ yếu đọc (trừ các bảng chat/cache/queue do serving tự ghi).
- **Serving** là một app FastAPI duy nhất: web UI tĩnh + REST API + các service
  xử lý hội thoại. Hội thoại được điều phối bằng **đồ thị LangGraph** (turn /
  knowledge-QA / hybrid); phần tính toán nặng (advisory) chạy nền qua **hàng đợi
  bền (durable queue)**.
- **Langfuse** là sink quan sát (observability) duy nhất — thay cho panel debug
  in-app đã gỡ (2026-06-18). Toàn bộ helper quan sát **degrade im lặng** khi
  Langfuse tắt.

Các package top-level mới: `observability/` (client Langfuse, run-trace helper,
prompt service) và `domain/` (Pydantic model dùng chung).

### Nguyên tắc thiết kế xuyên suốt

1. **Một cổng LLM duy nhất** — mọi lời gọi Gemini (trích hồ sơ, phân loại
   intent, OCR, QA, synthesis, judge…) đều đi qua `services/inference/gateway.py`,
   nơi xử lý chung retry, fallback model, xoay vòng API key, telemetry và link
   trace.
2. **Deterministic trước, LLM sau** — luật/regex/từ điển luôn được thử trước;
   LLM chỉ dùng cho việc máy không làm nổi. Đặc biệt: chấm điểm gợi ý, sinh câu
   trả lời tư vấn cuối, và phân xử mâu thuẫn điểm chuẩn là **thuần
   deterministic**, không qua LLM.
3. **Suy giảm có kiểm soát (graceful degradation)** — LLM lỗi không bao giờ làm
   sập luồng: mỗi điểm gọi có fallback (rule-based, keyword, nối chuỗi…) và log
   warning. Người dùng luôn nhận được câu trả lời.
4. **Dữ liệu luôn kèm nguồn gốc** — mỗi bản ghi mang `source_url`, `trust_level`
   (1–5), `confidence_score`. Dữ liệu cùng một chương trình từ các nguồn khác
   nhau được **giữ thành các dòng riêng** (không ghi đè) để tầng tư vấn phát hiện
   và xử lý mâu thuẫn.
5. **Idempotent mọi nơi** — re-crawl/re-ingest an toàn nhờ upsert theo khóa tự
   nhiên, content-hash để bỏ qua nội dung không đổi, migration `IF NOT EXISTS`.
6. **Quan sát được nhưng không bắt buộc** — mỗi node, mỗi lời gọi LLM đều phát
   span/generation lên Langfuse khi bật; tắt thì toàn bộ no-op.

---

## 2. Backend — các luồng hoạt động

### 2.1 Vòng đời một tin nhắn chat (turn graph)

Đây là luồng "xương sống". Từ 2026-06-18, mỗi lượt chat chạy qua một **đồ thị
LangGraph** (`services/chat/turn_graph.py::build_turn_graph`, gọi tại
`ConversationService.handle_user_message`):

```
Browser ──POST /api/sessions/{token}/messages──► turn_graph.invoke(state)
   ▲                                                  │
   │ poll GET /api/sessions/{token} (1.2s/lần)        │ guards: reset / rejection /
   │                                                  │ continue / correction
   │                                                  ▼
   │                              intent_router (node) → conditional routing
   │                     ┌────────────────────────────┴───────────────────┐
   │                     │ trả lời ngay:               enqueue run nền:    │
   │                     │ • conversational            • ADVISORY_FLOW     │
   └── kết quả ◄─────────┤ • knowledge_qa subgraph     • HYBRID            │
                         │ • clarification               (durable queue,   │
                         │ • out-of-scope                 polling)         │
                         └────────────────────────────────────────────────┘
```

- **Phiên ẩn danh**: không có tài khoản. Mỗi phiên là một token ngẫu nhiên lưu
  trong localStorage của browser; hồ sơ học sinh gắn với phiên.
- **Intent Router** (`services/chat/intent_router.py`) dùng Gemini phân loại tin
  nhắn vào **7 nhánh**; nếu LLM không khả dụng thì rơi xuống bộ phân loại từ khóa
  tiếng Việt không dấu (deterministic). System prompt của router được nạp qua
  **Langfuse PromptService** (có fallback cục bộ).

| Nhánh | Khi nào | Xử lý |
|---|---|---|
| `ADVISORY_FLOW` | "25 điểm A00 nên chọn trường nào" | Thu thập hồ sơ → enqueue run tư vấn |
| `KNOWLEDGE_QA` | "Học phí UET bao nhiêu" | RAG một (trường, chủ đề), trả lời ngay |
| `HYBRID` | "So sánh UET và HUST về điểm chuẩn lẫn học phí" | Advisory + RAG song song → tổng hợp |
| `CONVERSATIONAL` | Chào hỏi, cảm ơn, lo lắng thi cử | Trả lời mẫu; mời quay lại luồng tư vấn dở |
| `CLARIFICATION` | "Học phí trường này" (chưa biết trường nào) | Hỏi lại thông tin thiếu |
| `RESET_PROFILE` | "Xóa hồ sơ, tư vấn cho em gái em" | Làm lại hồ sơ từ đầu |
| `OUT_OF_SCOPE` | Ngoài chủ đề tuyển sinh | Từ chối lịch sự |

- Router dùng hồ sơ hiện có để **giải đại từ** ("trường này" → trường đang quan
  tâm), nhờ đó hội thoại nhiều lượt diễn ra tự nhiên.
- HTTP response trả về **ngay lập tức**; nếu có run nền, client tự poll trạng
  thái phiên cho tới khi `completed`/`failed` rồi render câu trả lời (markdown,
  hiệu ứng typewriter).

**Thực thi run nền — hàng đợi bền.** Run advisory/hybrid được ghi vào bảng
`chat_advisory_runs` (migration 018) và một **background worker**
(`services/chat/run_queue_worker.py`) nhận việc bằng `SELECT … FOR UPDATE SKIP
LOCKED`, chạy pipeline rồi cập nhật kết quả. Khác bản nháp cũ chỉ dùng
`ThreadPoolExecutor` trong tiến trình: hàng đợi bền giúp run sống sót và không
mất khi nhiều request đến cùng lúc.

### 2.2 Thu thập hồ sơ (slot filling)

Trước khi tư vấn cần đủ **5 slot bắt buộc**: năm tuyển sinh, tổng điểm, phương
thức xét tuyển, ngành quan tâm, tổ hợp môn (nơi ở và ngân sách học phí là tùy
chọn). Cách điền:

1. **Tier-0 deterministic**: câu trả lời ngắn cho đúng slot đang hỏi (vd "26.5")
   được parse bằng regex, *không tốn lời gọi LLM*. Một "lưới an toàn" luôn thử
   parse năm + slot đang chờ bất kể intent.
2. **LLM trích delta**: với câu dài, Gemini trích *chỉ các trường thay đổi*
   (không bao giờ trả nguyên hồ sơ), validate (vd điểm không vượt thang phương
   thức) rồi merge vào hồ sơ trong DB (JSONB).
3. **Ngành học có 2 lớp**: ngành user *nói rõ* và ngành hệ thống *suy ra*; tầng
   truy vấn dùng hợp của cả hai. Tên ngành tự do được quy về canonical qua bộ
   phân giải 3 tầng (`services/profile/major_resolver.py`), có **cổng intent**
   (chỉ chạy khi câu nói có dấu hiệu sở thích/định hướng, tránh ép ngành cho câu
   hỏi "học phí UET"):
   - **Tầng 1 — alias/từ điển** (free): exact → substring → fuzzy `thefuzz.ratio
     ≥ 85`.
   - **Tầng 2 — embedding** (pgvector trên `program_catalog_embeddings`): mạnh khi
     score ≥ 0.55; tự quyết khi có ứng viên ≥ 0.70 hoặc top-1 hơn top-2 ≥ 0.08.
   - **Tầng 3 — LLM chọn trong shortlist** khi tầng 2 có ứng viên nhưng không
     phân định rõ; LLM lỗi → lấy ứng viên tầng-2 cao nhất.
4. Thiếu slot nào hỏi đúng slot đó theo thứ tự cố định; đủ slot → phiên chuyển
   `ready` và run tư vấn được enqueue.
5. **Sửa thông tin sau khi đã có kết quả** (vd "à điểm em là 25 thôi") được phát
   hiện deterministic → tự chạy lại tư vấn, kèm ghi chú điều chỉnh.

### 2.3 Luồng tư vấn — pipeline LangGraph 6 node

Phần "não" là một đồ thị LangGraph **tuyến tính, cố định** (`graph.py`; không có
nhánh điều kiện, không tool-calling). Node ở `agents/`, state ở `domain/models.py`:

```
profile → retrieve → conflict → reason → policy → explain
```

| Node | Nhiệm vụ | LLM? |
|---|---|---|
| **profile** | Dựng `StudentProfile`; khi gọi từ chat, hồ sơ đã thu thập sẵn nên chỉ kiểm tra slot thiếu | Có (fallback rule-based) |
| **retrieve** | Query Postgres: chương trình khớp năm/ngành/trường + điểm chuẩn lịch sử; lọc theo tổ hợp môn | Không |
| **conflict** | Phát hiện & phân xử mâu thuẫn giữa các nguồn | Một phần |
| **reason** | Chấm điểm từng chương trình → xếp band `safe / match / reach / unknown` | Không |
| **policy** | Guardrails: chặn phát ngôn cấm, cảnh báo thiếu dữ liệu, lọc gợi ý không nguồn | Hiếm khi |
| **explain** | Dựng câu trả lời markdown tiếng Việt từ template: top gợi ý + lý do + lưu ý + trích dẫn | Không |

**Xử lý mâu thuẫn (điểm đặc trưng của hệ thống).** Vì mỗi nguồn là một dòng
riêng, node conflict gom các dòng cùng (trường, năm, ngành, phương thức) và so
giá trị:

- **Mâu thuẫn chỉ tiêu (quota)**: so theo 4 trục — độ tin cậy nguồn, số nguồn
  đồng thuận, độ mới, confidence. Một nguồn thắng rõ trên mọi trục → tự chọn.
  Không phân định được → **nhờ LLM phân xử**, chỉ chấp nhận khi LLM tự tin cao;
  còn lại đánh dấu *chưa giải quyết*.
- **Mâu thuẫn điểm chuẩn (cutoff)**: **không bao giờ dùng LLM**. Nếu giá trị mâu
  thuẫn làm *đổi kết luận* với điểm thí sinh → để *chưa giải quyết* + đánh dấu
  trường dữ liệu không chắc chắn; nếu không đổi kết luận → lấy nguồn tin cậy nhất
  nhưng vẫn liệt kê mọi giá trị cho minh bạch.
- Mâu thuẫn chưa giải quyết làm **hạ band** gợi ý và được nêu rõ trong câu trả
  lời ("Nguồn X ghi 120, nguồn Y ghi 150 — em nên kiểm tra trang chính thức").

**Chấm điểm (reason)** thuần luật: khớp ngành +0.35, khớp tổ hợp +0.40, khớp
trường +0.15, so điểm với điểm chuẩn lịch sử (chỉ với phương thức thang 30) cho
điểm cộng hoặc *cap* band xuống nếu sát/dưới ngưỡng/dữ liệu dao động. Thiếu slot
quan trọng → band buộc về `unknown`.

### 2.4 Luồng hỏi đáp kiến thức (Knowledge QA / RAG) — qa_graph

Knowledge QA đã đóng gói thành **subgraph LangGraph dùng lại được**
(`services/knowledge/qa_graph.py::build_kqa_graph`), ẩn sau
`KnowledgeQAService.answer()` (chữ ký không đổi), được gọi bởi cả luồng inline,
fan-out hybrid và compare:

```
embed → retrieve_school → augment_national → gate(min_score) → generate
```

1. **embed** câu hỏi: `gemini-embedding-001`, **768 chiều**, có L2-normalize
   (cache LRU 512 entry trong tiến trình).
2. **retrieve_school**: cosine **top-5** trong `knowledge_chunks` theo phạm vi
   (trường, chủ đề; chunk topic NULL luôn là ứng viên). Trước đó câu hỏi đi qua
   **bộ lọc chương trình pg_trgm**: `word_similarity(program, question)`; nếu có
   program đạt **≥ 0.5** thì thêm điều kiện lọc đúng program, không thì truy vấn
   thuần vector.
3. **augment_national**: cộng thêm **top-3** từ phạm vi quốc gia (MOET) với ngân
   sách riêng — quy định của Bộ luôn có mặt mà không chèn ép dữ liệu trường.
4. **gate (cổng chống bịa)**: nếu không có chunk nào đạt độ tương đồng **≥ 0.5**
   → trả "chưa có dữ liệu" mà *không gọi LLM*.
5. **generate**: Gemini trả lời *chỉ dựa trên các đoạn trích được đưa vào*, kèm
   danh sách nguồn nó thực sự dùng → câu trả lời luôn có trích dẫn URL.

**Semantic cache** (migration 019, `services/knowledge/qa_cache.py`): câu hỏi đã
trả lời được lưu kèm embedding 768d + dấu phiên bản phụ thuộc. Câu hỏi sau có
embedding **≥ 0.95** với một mục cache → tái dùng câu trả lời, **trừ khi** một lần
ingest đã *bump phiên bản scope* (làm cũ cache, buộc tính lại). TTL 30 ngày; cache
tắt khi `school`/`topic` = None (để probe/eval lấy retrieval sạch). Chỉ cache câu
trả lời đạt ngưỡng (`confidence ≥ 0.5`).

### 2.5 Luồng hybrid / so sánh — hybrid_graph

Cho câu hỏi trộn cả tư vấn lẫn kiến thức ("so sánh UET và HUST về điểm chuẩn lẫn
học phí"), điều phối bằng `services/chat/hybrid_graph.py`:

1. Chạy **song song** hai nhánh: advisory pipeline (nếu cần) và **knowledge
   fan-out** — một query RAG (qua qa_graph) cho từng cặp (trường × chủ đề); một
   query lỗi không làm chết các query còn lại.
2. **Synthesis agent** (LLM) ghép hai nhánh thành câu trả lời có cấu trúc, ràng
   buộc "không thêm thông tin ngoài hai khối dữ liệu"; LLM lỗi → nối các khối
   deterministic. System prompt nạp qua Langfuse PromptService.
3. Nếu hồ sơ chưa đủ để tư vấn: trả phần kiến thức ngay, đồng thời hỏi tiếp slot
   còn thiếu.

### 2.6 Inference Gateway — cổng LLM duy nhất

Mọi lời gọi LLM đi qua một gateway với vòng đời thống nhất:

```
caller → registry chọn model theo agent → gọi Gemini (qua key pool)
       → JSON hỏng?  → STRUCTURE_FAILURE → retry cùng model → fallback model khác
       → API lỗi cứng? → InferenceError  → caller tự fallback deterministic
       → mỗi attempt → record_generation(...) lên Langfuse
```

- **Registry per-agent**: mỗi tác vụ (trích hồ sơ, QA, OCR, synthesis, judge…)
  được gán model chính/dự phòng riêng (chủ yếu `gemini-2.5-flash-lite`, nâng lên
  `gemini-2.5-flash` cho QA/synthesis), số retry và định dạng output
  (JSON/free-text). Temperature mặc định **0.0** — ưu tiên tái lập.
- **Key pool**: nhiều API key Gemini xoay vòng round-robin. Gặp 429/401/403/5xx →
  key đó vào "cooldown" (mặc định 60s hoặc theo `retryDelay` server trả về) và
  thử key kế tiếp; hết key khả dụng mới chịu lỗi.
- **Prompt handle**: `InferenceRequest` có thể mang một prompt handle (từ
  PromptService) để generation trên Langfuse **link ngược về phiên bản prompt**.
- **Telemetry** ghi lại từng attempt (agent, model, kết quả, có fallback không).

### 2.7 Observability — Langfuse là sink duy nhất

> **Thay đổi lớn (2026-06-18).** Panel debug trace in-app cũ (bảng Postgres
> `advisory_trace_events`, endpoint `GET /api/sessions/{token}/trace`, module JS
> `trace.js`, cột phải `#trace-panel`) đã **gỡ bỏ hoàn toàn**. Bảng
> `advisory_trace_events` (migration 011) vẫn còn nhưng **dormant** (không còn
> ghi). Không còn cờ `ADVISORY_DEBUG_UI`.

Quan sát hiện tại đi qua một sink duy nhất là **Langfuse** (package
`observability/`):

- `observability/langfuse_client.py` — `get_langfuse()` singleton lazy; bật bằng
  `ADVISORY_LANGFUSE_ENABLED`, đọc `LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST`. Trả
  `None` và **no-op toàn bộ** khi tắt hoặc thiếu key. Có hook `_mask()` (seam cho
  redaction PII về sau, hiện passthrough).
- `observability/run_trace.py` — root span `advisory_run_trace`/`turn_trace`,
  `stage_span` cho từng stage pipeline, `record_generation` cho từng lời gọi
  Gemini (kèm model, prompt/response thô, token usage từ
  `InferenceResult.usage`, latency, `attempt`, `used_fallback`, `failure_type`).
  Trace-id suy ra từ `run_id`; `session_id = session_token`.
- `services/tracing/agent_tracer.py` (`@traced`) bọc 6 node advisory → chỉ mở
  `stage_span` (phần ghi DB cũ đã bỏ); `extractors.py` ánh xạ state vào/ra span.
- **Không dùng `CallbackHandler`** của langchain — gateway bỏ qua langchain, tự
  emit generation bằng SDK Langfuse (`start_as_current_generation`).
- **Score config** (faithfulness, answer_relevance, intent_correct,
  helpfulness…) đã *tạo schema* trên Langfuse (`scripts/seed_langfuse.py`) nhưng
  **chưa được emit ở runtime** — hiện chỉ là template cho chấm tay/eval offline.
- Langfuse v3 self-host chạy ở compose stack riêng; app stack (`advisory-db`)
  không đổi. Mọi helper degrade im lặng.

---

## 3. Data — ingestion và luồng dữ liệu

Hệ thống ingest **hai loại dữ liệu** bằng hai pipeline riêng:

| | Structured (tuyển sinh) | Unstructured (kiến thức) |
|---|---|---|
| Nội dung | Chỉ tiêu, phương thức, tổ hợp, điểm chuẩn | Học phí, học bổng, KTX, quy chế, mô tả ngành… |
| Nguồn | Trang tuyển sinh, đề án PDF, aggregator | Web, PDF crawl, văn bản MOET, PDF local, **API curriculum (NEU Strapi)** |
| Đích | `canonical_admission_records`, `cutoff_records` | `knowledge_chunks` (pgvector) |
| Phục vụ | Advisory pipeline | Knowledge QA (RAG) |

### 3.1 Pipeline structured: từ URL đến bản ghi canonical

```
Source Registry → Fetch → Route → Parse → Extract → Normalize → Upsert DB
```

1. **Source Registry** — danh mục nguồn theo trường (seed JSON): URL, loại,
   **trust_level 1–5**, priority, cờ chính thống, `parser_profile`.
2. **Fetch** — HTTP GET retry backoff lũy thừa, User-Agent xoay vòng, SHA-256 nội
   dung. SSL verify **tắt mặc định** (nhiều site `.gov.vn` hỏng cert) — bật bằng
   `ADVISORY_FETCH_VERIFY_SSL`.
3. **Route** — đoán loại tài liệu theo Content-Type → đuôi URL → magic bytes.
4. **Parse** — parser chuyên biệt theo trường trích thẳng ra facts (kèm trích
   `content_label`: breadcrumb/title/slug); nếu không có thì parser generic
   (BeautifulSoup/pdfminer) chỉ trích text + bảng cho bước extract.
5. **Extract** — regex + nhận diện bảng theo từ khóa cột, mỗi fact kèm confidence.
   Nếu confidence trung bình < 0.6 hoặc không trích được → **fallback Gemini**
   trích theo schema JSON (văn bản dài cắt chunk 30KB), rồi merge hai cách.
6. **Normalize** — quy về canonical bằng **4 từ điển JSON** (programs, methods,
   subjects, combo→method rules), mỗi từ điển có `_shared` + override theo trường:
   tên/mã ngành → `program_id` (exact → substring → fuzzy ≥85); phương thức chữ →
   mã chuẩn (suy ra từ tổ hợp nếu nguồn không ghi); tổ hợp → {mã, môn}; chỉ tiêu
   chữ → {giá trị, kiểu exact/range/approximate}.
7. **Upsert** — `canonical_admission_records` khóa **(trường, năm, ngành, phương
   thức, source_url)**. Khóa chứa `source_url` là chủ ý: cùng chương trình từ 2
   nguồn tồn tại thành 2 dòng → tầng tư vấn mới phát hiện được mâu thuẫn. Re-crawl
   chỉ cập nhật, không nhân đôi.

Dữ liệu trung gian lưu lại để audit: `raw_documents` (bytes gốc + headers) và
`extracted_facts` (facts trước chuẩn hóa, kèm confidence + phương pháp trích).

### 3.2 Điểm chuẩn lịch sử (cutoff) — đường ingest riêng

`python -m ingestion.ingest_cutoffs`, hai chế độ:

- **Seed JSON đã kiểm tay** — validate *all-or-nothing*: một dòng lỗi là báo toàn
  bộ và không ghi gì (bảo toàn dữ liệu curated).
- **Scrape aggregator** (tuyensinh247) — lỗi dòng nào bỏ dòng đó (best-effort).

Trường phương thức lưu **mã** (không phải tên hiển thị) kèm `score_scale` (thang
30 điểm THPT, thang 100 ĐGTD…) để reasoning so điểm đúng thang. Đích:
`cutoff_records`, upsert per-source.

### 3.3 Pipeline kiến thức: từ tài liệu đến vector

Bốn đường vào, hội tụ về cùng một flow:

- Registry URL theo trường (`ingestion.knowledge.pipeline --school/--all`);
- Manifest PDF đã crawl đánh dấu "keep" (`ingest_manifest`);
- Văn bản quy chế quốc gia, scope `MOET` (`ingest_national`);
- **API curriculum NEU (Strapi)** — `ingestion/knowledge/neu_api.py` đọc JSON
  curriculum (do trang HTML NEU chặn `http_fetch`), trích mô tả ngành thành
  nguồn program-overview;
- Thư mục PDF local (tự phân loại trường/năm bằng LLM đọc trang đầu).

```
Tài liệu → trích text (hybrid text-layer/OCR) → đánh dấu [Trang N]
        → chunk (chiến lược) → embed 768d → knowledge_chunks
```

- **Trích text hybrid**: trang có text layer (≥50 ký tự) dùng luôn; trang scan
  render ảnh ~200 DPI → **Gemini vision OCR**. Có cơ chế phát hiện **OCR thoái
  hóa** (lặp vô hạn một ký tự, thường do bảng merge cell): output quá dài hoặc
  >80% là một ký tự → retry temperature 0.3; vẫn hỏng → bỏ trang đó.
- **Chunking — 3 chiến lược** (`ingestion/knowledge/chunker.py`):
  - `size` (mặc định): cắt theo ranh giới đoạn/câu, **1800 ký tự, overlap 256**;
  - `by_section`: cắt theo heading markdown `## `; mỗi section thành một chunk có
    **header `{nhãn chương trình} — {tên section}`** để định danh chương trình +
    chủ đề nằm ngay trong embedding; trang không có heading → degrade về size split
    nhưng vẫn gắn nhãn chương trình;
  - `whole_page`: cả trang thành một chunk (tốt cho trang program-overview ngắn,
    tự chứa); trang dài hơn **8000 ký tự** → degrade size split để không cắt cụt.
- **Embedding**: `gemini-embedding-001`, 768 chiều, lưu pgvector chỉ mục **HNSW
  (cosine)**. **Tái dùng embedding theo content-hash (SHA-256)**: chunk trùng nội
  dung với bất kỳ chunk nào đã có → lấy lại vector cũ, không embed lại → re-ingest
  gần như miễn phí.
- **Idempotency** hai tầng: tài liệu trùng hash → bỏ qua; chunk upsert theo
  (source_url, span_start, span_end).
- **Bump cache version**: mỗi lần ingest bump phiên bản scope của semantic QA cache
  → câu trả lời cache cũ tự cũ hóa, không phục vụ dữ liệu lỗi thời.

### 3.4 Schema database theo domain

**20 file migration** idempotent (`db/migrations/001…019`, hai file cùng prefix
`014` nên file count = 20 trong khi số đỉnh = 019), áp tuần tự bởi
`db/setup_db.py`. Schema chia 4 nhóm:

| Nhóm | Bảng | Vai trò |
|---|---|---|
| **Ingestion structured** | `source_registry`, `raw_documents`, `extracted_facts` (`discovered_resources` đã drop ở 014) | Danh mục nguồn + dấu vết crawl (audit/lineage) |
| **Canonical store** | `canonical_admission_records`, `cutoff_records` | Sự thật chuẩn hóa, đa dòng per-source, có trust/confidence |
| **Knowledge (RAG)** | `knowledge_documents`, `knowledge_chunks` (vector 768 + HNSW + GIN trgm trên `program`), `program_catalog_embeddings`, `knowledge_qa_cache` + `knowledge_qa_cache_version` | Corpus RAG + embedding tên ngành + semantic cache |
| **Chat & vận hành** | `chat_sessions` (hồ sơ JSONB), `chat_messages`, `chat_advisory_runs` (+ hàng đợi 018), `flow_state`, `advisory_trace_events` (011, dormant) | Phiên, transcript, run nền, hàng đợi, trace cũ |

### 3.5 Census dữ liệu hiện tại

**Canonical store** (dev DB `admission`, FACTS.md 2026-06-19):

| Bảng | Count |
|---|---|
| canonical_admission_records — hust | 136 |
| canonical_admission_records — vnu_uet | 20 |
| cutoff_records (hust 699 + vnu_uet 16) | **715** |
| program_catalog_embeddings | 82 |

**Knowledge corpus** — đang biến động mạnh:
- FACTS.md 2026-06-19 (dev DB): 93 documents / **692 chunks** (tăng từ 18 doc /
  406 chunk ngày 2026-06-16 nhờ scraper HUST + chiến lược `by_section`).
- Census 2026-06-20 (sau khi ingest API curriculum NEU): **~1.922 chunks**:

| Trường | Chunks | Chủ đề (chunks) |
|---|---|---|
| HUST | 462 | program_overview 301, admission_policy 78, tuition 13, (null) 70 |
| NEU | 1.252 | program_overview 1.160, (null) 92 |
| VNU-UET | 56 | program_overview 28, admission_policy 25, tuition 3 |
| MOET | 152 | admission_policy 19, (null) 133 |

---

## 4. Các cơ chế nền tảng khác

**Suy giảm có kiểm soát ở mọi điểm gọi LLM.** Bảng fallback tiêu biểu:

| Điểm gọi LLM | Khi LLM lỗi |
|---|---|
| Phân loại intent | Bộ phân loại từ khóa tiếng Việt không dấu |
| Trích hồ sơ | Regex + từ điển alias |
| Phân giải ngành (tầng 3) | Lấy ứng viên embedding cao nhất |
| Phân xử mâu thuẫn quota | Đánh dấu "chưa giải quyết", hạ band gợi ý |
| Knowledge QA | Trả "chưa có dữ liệu" (không bịa) |
| Synthesis hybrid | Nối các khối kết quả deterministic |
| OCR trang PDF | Bỏ trang lỗi, tiếp tục các trang khác |
| Langfuse / PromptService tắt-lỗi | No-op / dùng prompt fallback cục bộ |

**Quản lý prompt — Langfuse PromptService (pilot 2026-06-18).**
`observability/prompts.py` nạp/biên dịch system prompt từ Langfuse (label
`production`, cache TTL 300s), có fallback cục bộ (mặc định tắt). Phạm vi pilot =
**3 agent**: `intent_router`, `synthesis_agent`, `qa_service`. Sửa prompt không
cần deploy lại; generation link ngược phiên bản prompt.

**Cô lập database khi test.** `pytest` tự chuyển mọi kết nối sang database
`admission_test` (tạo + migrate tự động) trước khi chạy — fixture có TRUNCATE
không bao giờ đụng dữ liệu dev trong `admission`.

**Mock dữ liệu mâu thuẫn.** `ADVISORY_MOCK_CONFLICTS=1` để node retrieve trả bộ
ứng viên giả có quota mâu thuẫn sẵn — test luồng conflict không cần dữ liệu thật.

**Console UTF-8 trên Windows.** Các CLI ingestion tự cấu hình lại stdout/stderr
sang UTF-8 để tên ngành tiếng Việt không vỡ.

**Frontend tối giản, không framework.** Vanilla JS chia module (messages, theme,
typewriter, toasts…), markdown render bằng marked.js, trạng thái phiên trong
localStorage. Realtime bằng polling (~1.2s) thay vì WebSocket.

**Điểm cần biết khi vận hành:**
- Run nền không có timeout cứng — lời gọi LLM treo sẽ giữ worker; client thấy
  phiên kẹt ở `running`.
- Score config Langfuse đã tạo schema nhưng chưa emit ở runtime.
- Đổi `EMBEDDING_DIM` đòi migrate cột vector + re-embed toàn corpus.

---

## 5. Kỹ thuật áp dụng và hiệu quả

Bảng tổng hợp các kỹ thuật chính và **hiệu quả đo được** (số liệu: báo cáo eval
`docs/superpowers/evals/2026-06-10-knowledge-qa-flash-vs-flash-lite.md`, FACTS.md
2026-06-19, ma trận edge-case). Không có số nào ước lượng.

### 5.1 Chất lượng RAG — đo bằng golden set có judge

**Kỹ thuật eval**: golden set 32 case (26 trả lời được + 6 cần *abstain*),
**retrieval đóng băng** (chunk lưu sẵn lúc curate → chỉ đo biến model, không lẫn
nhiễu retrieval), chấm **lai**: deterministic (`citation_f1`, `abstention_correct`)
+ **LLM judge cố định `gemini-2.5-flash`** chấm `faithful`/`correct`. Cổng quyết
định: faithfulness/abstention **không được tụt**, correctness/citation trong sai
số ±0.05.

Kết quả (2026-06-10):

| Metric | gemini-2.5-flash (đang dùng) | gemini-2.5-flash-lite |
|---|---|---|
| **Faithfulness** (bám nguồn) | **0.958** | 0.957 |
| **Correctness** (đúng nội dung) | **0.769** | 0.615 |
| **Citation F1** (trích đúng nguồn) | **0.656** | 0.604 |
| **Abstention accuracy** (biết im lặng đúng lúc) | **0.938** | 0.906 |

- **Hiệu quả**: faithfulness **0.958** xác nhận ràng buộc "chỉ trả lời từ đoạn
  trích" hoạt động — model gần như không bịa ngoài context. Abstention **0.938**
  xác nhận **cổng chống bịa (min_score 0.5)** chặn được câu hỏi ngoài corpus.
- **Quyết định model**: flash-lite **FAIL** (correctness tụt 0.154, ngoài sai
  số) → giữ `gemini-2.5-flash` cho QA. Đây là bằng chứng định lượng cho lựa chọn
  model, không phải cảm tính.

### 5.2 Throttle + retry cho key pool free-tier

**Kỹ thuật**: chèn delay giữa các call (`EVAL_CALL_DELAY_SECONDS≈2.0`) + retry
backoff (`RETRY_WAIT≈65s`), xoay vòng key pool với cooldown per-key.
**Hiệu quả**: run eval 2026-06-10 **0 lỗi sinh / 0 lỗi quota** trên 32×2 case,
trong khi các run *không throttle* trước đó **hỏng ~50% lời gọi**. Cùng cơ chế
áp cho sinh dataset (`scripts/gen_eval_dataset.py`) và coverage probe.

### 5.3 Cổng chống bịa + RAG có trích dẫn

**Kỹ thuật**: gate cosine **≥ 0.5** *trước* khi gọi LLM; nếu không đạt trả "chưa
có dữ liệu" (không tốn LLM, không bịa). LLM chỉ thấy đoạn trích, phải kèm nguồn
thực dùng. **Hiệu quả**: thể hiện qua faithfulness 0.958 + abstention 0.938 ở §5.1;
chi phí giảm vì câu hỏi ngoài corpus bị chặn *trước* lời gọi sinh.

### 5.4 Bộ lọc chương trình pg_trgm

**Kỹ thuật**: `word_similarity(program, question)` (extension pg_trgm, chỉ mục GIN
— migration 020), ngưỡng **0.5**. **Hiệu quả** (commit 21d972c): ngành được gọi
đúng tên đạt ~1.0 (cửa sổ khớp = nhãn), còn câu hỏi policy/tuition chỉ trùng một
từ phổ biến (vd "trường" với "Quản lý thị trường") tối đa ~0.44 → ngưỡng 0.5 tách
**sạch** va chạm từ phổ biến, tránh khóa nhầm retrieval vào một chương trình.

### 5.5 Semantic cache + content-hash reuse

- **Semantic cache** (sim ≥ 0.95, TTL 30d, version-gated): câu hỏi gần giống dùng
  lại câu trả lời, tự cũ hóa khi ingest. **Hiệu quả**: tiết kiệm embed+generate
  cho câu lặp; *đúng đắn* nhờ version bump (không phục vụ dữ liệu lỗi thời). Hiện
  bảng cache trống (0 dòng) cho tới khi có lưu lượng thật.
- **Content-hash embedding reuse** (SHA-256): chunk trùng nội dung tái dùng
  vector. **Hiệu quả**: re-ingest gần như miễn phí phần embedding — quan trọng khi
  corpus tăng nhanh (18→93 doc rồi ~1.922 chunk).

### 5.6 Chunking `by_section` + nhãn chương trình

**Kỹ thuật**: cắt theo heading, nhúng nhãn `{chương trình} — {section}` vào chunk.
**Hiệu quả**: corpus kiến thức tăng **18 → 93 document, 406 → 692 chunk**
(2026-06-16 → 2026-06-19) khi áp scraper program-overview + `by_section`; định
danh chương trình nằm sẵn trong embedding giúp bộ lọc §5.4 và retrieval đúng ngành.

### 5.7 Deterministic-first (tiết kiệm + tái lập)

**Kỹ thuật**: regex/từ điển/luật trước, LLM sau; chấm điểm + sinh câu trả lời tư
vấn + phân xử cutoff thuần luật. **Hiệu quả**: câu trả lời ngắn điền slot (vd
"26.5") *không tốn LLM*; kết quả tư vấn tái lập (temp 0.0); phân xử điểm chuẩn
không bao giờ bịa vì không gọi LLM.

### 5.8 Tuân thủ edge-case (đo hành vi đầu-cuối)

Đối chiếu 25 case trong `docs/edge-case.md`: **17 pass / 4 partial / 4 fail**
(baseline 2026-06-04: **8 / 3 / 14**). **Hiệu quả**: hơn gấp đôi số case đạt.
Gốc còn lại tập trung một chỗ: model hồ sơ phẳng cho nơi-ở/học-phí + reasoning bỏ
qua hai trường này (cụm "structured preferences": EC-07/08/11/19/20/25).

### 5.9 Độ tin cậy kỹ thuật (regression safety)

**Kỹ thuật**: test cô lập DB tự động (`admission_test`), suite lớn.
**Hiệu quả**: **1.122 pass / 1 skip** trên **1.123 test** (~14s với Docker DB),
0 error. Skip duy nhất là e2e cần dump dữ liệu thật ngoài repo.

---

## 6. Bản đồ entry point

| Việc cần làm | Lệnh |
|---|---|
| Dựng DB (Docker) + migrate + seed | `docker compose up -d --wait db` rồi `python -m db.setup_db` |
| Ingest dữ liệu tuyển sinh một trường | `python -m ingestion.main --school hust` (`--list` để xem trường) |
| Ingest điểm chuẩn lịch sử | `python -m ingestion.ingest_cutoffs --seed` |
| Ingest kho kiến thức | `python -m ingestion.knowledge.pipeline --all` (+ `ingest_manifest`, `ingest_national`, `neu_api`) |
| Kiểm tra corpus RAG | `python -m ingestion.knowledge.verify_corpus` |
| Chạy web app | `python -m uvicorn web.app:build_app --factory --reload` |
| Demo advisory qua CLI | `python main.py --query "..."` |
| Test (tự cô lập sang `admission_test`) | `python -m pytest -q` |
| Eval chất lượng QA (flash vs flash-lite) | `python -m eval.knowledge_qa.run` |
| Sinh dataset eval grounded | `python -m scripts.gen_eval_dataset [--push]` |
| Coverage probe corpus | `python -m scripts.coverage_probe` |
| Seed score-config + prompt Langfuse | `python -m scripts.seed_langfuse` / `scripts.seed_langfuse_prompts` |
