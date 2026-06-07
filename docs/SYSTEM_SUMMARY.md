# Tổng quan hệ thống — Admission Advisory System

> Tài liệu tóm tắt toàn hệ thống: kiến trúc, các luồng backend, luồng dữ liệu và
> các cơ chế nền tảng. Cập nhật: 2026-06-06.

Hệ thống là một **trợ lý tư vấn tuyển sinh đại học Việt Nam có nhận biết mâu
thuẫn dữ liệu (conflict-aware)**. Nó crawl các nguồn chính thống (trang tuyển
sinh, đề án PDF, văn bản Bộ GD&ĐT), chuẩn hóa về một kho dữ liệu canonical trên
Postgres, rồi phục vụ một chat UI: thu thập hồ sơ học sinh qua hội thoại, gợi ý
ngành/trường phù hợp, trả lời câu hỏi kiến thức (học phí, học bổng, KTX…) bằng
RAG, và luôn nói rõ khi các nguồn dữ liệu mâu thuẫn nhau.

Phạm vi dữ liệu hiện tại: **HUST, VNU-UET** (dữ liệu tuyển sinh có cấu trúc),
**HUST, NEU, VNU-UET, MOET** (kho kiến thức RAG).

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
│     điểm chuẩn          │      │  ⑤ Chat services             │
│  ② Knowledge pipeline   │      │     session / intent /       │
│     PDF, văn bản → RAG  │      │     slot-filling / dispatch  │
└───────────┬─────────────┘      │       │                      │
            │ ghi                │  ⑥ Advisory pipeline         │
            ▼                    │     (LangGraph 6 node)       │
┌─────────────────────────┐      │  ⑦ Knowledge QA (RAG)        │
│  ③ Postgres 16 +        │◄─────┤       │                      │
│     pgvector (Docker)   │ đọc  │  ⑧ Inference Gateway         │
│  canonical store,       │      │     (mọi LLM call → Gemini)  │
│  knowledge chunks,      │      └──────────────────────────────┘
│  chat, trace            │
└─────────────────────────┘
```

- **Ingestion** chạy thủ công bằng CLI (`python -m ingestion.main`,
  `ingestion.knowledge.pipeline`…), không chạy theo lịch. Kết quả là dữ liệu
  trong Postgres — serving không bao giờ tự crawl.
- **Postgres + pgvector** là điểm gặp nhau duy nhất giữa hai phía: ingestion
  ghi vào, serving chỉ đọc (trừ các bảng chat/trace do serving tự ghi).
- **Serving** là một app FastAPI duy nhất: web UI tĩnh + REST API + các service
  xử lý hội thoại; phần tính toán nặng (advisory) chạy nền trong thread pool.

### Nguyên tắc thiết kế xuyên suốt

1. **Một cổng LLM duy nhất** — mọi lời gọi Gemini (trích xuất hồ sơ, phân loại
   intent, OCR, QA, synthesis…) đều đi qua `services/inference/gateway.py`,
   nơi xử lý chung retry, fallback model, xoay vòng API key và telemetry.
2. **Deterministic trước, LLM sau** — luật/regex/từ điển luôn được thử trước;
   LLM chỉ dùng cho việc máy không làm nổi (hiểu văn bản tự do, phân xử mâu
   thuẫn, tổng hợp câu trả lời). Đặc biệt: chấm điểm gợi ý và sinh câu trả lời
   cuối là **thuần deterministic**, không qua LLM.
3. **Suy giảm có kiểm soát (graceful degradation)** — LLM lỗi không bao giờ làm
   sập luồng: mỗi điểm gọi đều có fallback (rule-based, keyword, nối chuỗi…)
   và log warning. Người dùng luôn nhận được câu trả lời.
4. **Dữ liệu luôn kèm nguồn gốc** — mỗi bản ghi mang `source_url`,
   `trust_level` (1–5), `confidence_score`. Dữ liệu cùng một chương trình từ
   các nguồn khác nhau được **giữ thành các dòng riêng** (không ghi đè) để tầng
   tư vấn phát hiện và xử lý mâu thuẫn.
5. **Idempotent mọi nơi** — re-crawl/re-ingest an toàn nhờ upsert theo khóa tự
   nhiên, content-hash để bỏ qua nội dung không đổi, migration `IF NOT EXISTS`.

---

## 2. Backend — các luồng hoạt động

### 2.1 Vòng đời một tin nhắn chat

Đây là luồng "xương sống" — mọi luồng khác đều rẽ nhánh từ đây:

```
Browser ──POST /api/sessions/{token}/messages──► ConversationService
   ▲                                                  │
   │ poll GET /api/sessions/{token} (1.2s/lần)        │ 1. lưu message
   │                                                  │ 2. parse deterministic (slot đang chờ, năm…)
   │                                                  │ 3. Intent Router phân loại
   │                                                  ▼
   │                     ┌────────────────────────────┴───────────────────┐
   │                     │ trả lời ngay:               tạo run chạy nền:  │
   │                     │ • small-talk                • ADVISORY_FLOW    │
   └── kết quả ◄─────────┤ • Knowledge QA (1 câu hỏi)  • HYBRID           │
                         │ • hỏi tiếp slot còn thiếu     (ThreadPool,     │
                         │ • xin làm rõ (clarify)         polling)        │
                         └────────────────────────────────────────────────┘
```

- **Phiên ẩn danh**: không có tài khoản. Mỗi phiên là một token ngẫu nhiên lưu
  trong localStorage của browser; hồ sơ học sinh gắn với phiên, không gắn người.
- **Intent Router** (`services/chat/intent_router.py`) dùng Gemini phân loại
  tin nhắn vào **7 nhánh**; nếu LLM không khả dụng thì rơi xuống bộ phân loại
  từ khóa tiếng Việt không dấu (deterministic):

| Nhánh | Khi nào | Xử lý |
|---|---|---|
| `ADVISORY_FLOW` | "25 điểm A00 nên chọn trường nào" | Thu thập hồ sơ → chạy pipeline tư vấn |
| `KNOWLEDGE_QA` | "Học phí UET bao nhiêu" | RAG một (trường, chủ đề), trả lời ngay |
| `HYBRID` | "So sánh UET và HUST về điểm chuẩn lẫn học phí" | Advisory + RAG song song → tổng hợp |
| `CONVERSATIONAL` | Chào hỏi, cảm ơn, lo lắng thi cử | Trả lời mẫu có sẵn; mời quay lại luồng tư vấn dở |
| `CLARIFICATION` | "Học phí trường này" (chưa biết trường nào) | Hỏi lại thông tin thiếu |
| `RESET_PROFILE` | "Xóa hồ sơ, tư vấn cho em gái em" | Làm lại hồ sơ từ đầu |
| `OUT_OF_SCOPE` | Ngoài chủ đề tuyển sinh | Từ chối lịch sự |

- Router dùng hồ sơ hiện có để **giải đại từ** ("trường này" → trường em đang
  quan tâm), nhờ đó hội thoại nhiều lượt diễn ra tự nhiên.
- HTTP response trả về **ngay lập tức**; nếu có run chạy nền, client tự poll
  trạng thái phiên cho tới khi `completed`/`failed` rồi render câu trả lời
  (markdown, có hiệu ứng typewriter).

### 2.2 Thu thập hồ sơ (slot filling)

Trước khi tư vấn, hệ thống cần đủ **5 slot bắt buộc**: năm tuyển sinh, tổng
điểm, phương thức xét tuyển, ngành quan tâm, tổ hợp môn (nơi ở và ngân sách học
phí là tùy chọn). Cách điền:

1. **Tier-0 deterministic**: câu trả lời ngắn cho đúng slot đang hỏi (vd "26.5")
   được parse bằng regex, *không tốn lời gọi LLM*. Một "lưới an toàn" luôn thử
   parse năm + slot đang chờ bất kể intent.
2. **LLM trích delta**: với câu dài, Gemini trích ra *chỉ các trường thay đổi*
   (không bao giờ trả nguyên hồ sơ), sau đó được validate (vd điểm không vượt
   thang của phương thức) rồi merge vào hồ sơ trong DB (JSONB).
3. **Ngành học có 2 lớp**: ngành user *nói rõ* và ngành hệ thống *suy ra* từ
   ngữ cảnh; tầng truy vấn dùng hợp của cả hai. Tên ngành tự do được quy về
   ngành canonical qua bộ phân giải 3 tầng: **alias (từ điển) → embedding
   (pgvector trên `program_catalog_embeddings`) → LLM chọn trong shortlist**.
4. Thiếu slot nào hỏi đúng slot đó theo thứ tự cố định; đủ slot → phiên chuyển
   `ready` và run tư vấn được khởi động.
5. **Sửa thông tin sau khi đã có kết quả** (vd "à điểm em là 25 thôi") được
   phát hiện deterministic → tự động chạy lại tư vấn, kèm ghi chú điều chỉnh
   trong câu trả lời mới.

### 2.3 Luồng tư vấn — pipeline LangGraph 6 node

Phần "não" của hệ thống là một đồ thị LangGraph **tuyến tính, cố định** (không
có nhánh điều kiện, không tool-calling), chạy nền trong ThreadPoolExecutor:

```
profile → retrieve → conflict → reason → policy → explain
```

| Node | Nhiệm vụ | LLM? |
|---|---|---|
| **profile** | Dựng `StudentProfile`. Khi gọi từ chat, hồ sơ đã thu thập sẵn nên node chỉ kiểm tra slot thiếu | Có (fallback rule-based) |
| **retrieve** | Query Postgres: chương trình khớp năm/ngành/trường + lịch sử điểm chuẩn các năm trước; lọc theo tổ hợp môn | Không |
| **conflict** | Phát hiện & phân xử mâu thuẫn giữa các nguồn (chi tiết dưới) | Một phần |
| **reason** | Chấm điểm từng chương trình → xếp band `safe / match / reach / unknown` | Không |
| **policy** | Guardrails: chặn các phát ngôn cấm, cảnh báo thiếu dữ liệu, lọc gợi ý không có nguồn | Hiếm khi |
| **explain** | Dựng câu trả lời markdown tiếng Việt từ template: top gợi ý + lý do + lưu ý + nguồn trích dẫn | Không |

**Xử lý mâu thuẫn (điểm đặc trưng của hệ thống).** Vì mỗi nguồn là một dòng
riêng trong DB, node conflict gom các dòng cùng (trường, năm, ngành, phương
thức) và so giá trị:

- **Mâu thuẫn chỉ tiêu (quota)**: so các nguồn theo 4 trục — độ tin cậy nguồn,
  số nguồn đồng thuận, độ mới, confidence. Nếu một nguồn thắng rõ trên mọi trục
  → tự chọn. Nếu không phân định được → nhờ **LLM phân xử**, nhưng chỉ chấp
  nhận khi LLM tự tin cao; còn lại đánh dấu *chưa giải quyết được*.
- **Mâu thuẫn điểm chuẩn (cutoff)**: **không bao giờ dùng LLM**. Quy tắc: nếu
  các giá trị mâu thuẫn làm *đổi kết luận* với điểm của thí sinh (nguồn A bảo
  "trên điểm chuẩn", nguồn B bảo "sát ngưỡng") → để *chưa giải quyết* và đánh
  dấu trường dữ liệu không chắc chắn; nếu không đổi kết luận → lấy nguồn tin
  cậy nhất nhưng vẫn liệt kê mọi giá trị cho minh bạch.
- Mâu thuẫn chưa giải quyết làm **hạ band** gợi ý (safe → match…) và được nêu
  rõ trong câu trả lời ("Nguồn X ghi 120, nguồn Y ghi 150 — em nên kiểm tra
  trang chính thức").

**Chấm điểm (reason)** thuần luật: khớp ngành +0.35, khớp tổ hợp +0.40, khớp
trường +0.15, so điểm với điểm chuẩn lịch sử (chỉ với các phương thức thang 30)
cho điểm cộng hoặc *cap* band xuống nếu sát ngưỡng/dưới ngưỡng/dữ liệu dao động.
Thiếu slot quan trọng → band buộc về `unknown`.

**Policy** duy trì danh sách "phát ngôn bị chặn" (không bao giờ khẳng định chắc
chắn đậu; không phán xác suất khi chưa có điểm; điểm chuẩn cũ chỉ là tham
chiếu…), và loại mọi gợi ý không truy được về một nguồn cụ thể.

### 2.4 Luồng hỏi đáp kiến thức (Knowledge QA / RAG)

Cho câu hỏi factual ("học phí", "học bổng", "ký túc xá"…):

1. Embed câu hỏi (cùng model với corpus).
2. Tìm cosine top-5 trong `knowledge_chunks` theo phạm vi (trường, chủ đề),
   **cộng thêm top-3 từ phạm vi quốc gia (MOET)** với ngân sách riêng — quy
   định của Bộ luôn có mặt mà không chèn ép dữ liệu trường.
3. **Cổng chống bịa**: nếu không có chunk nào đạt độ tương đồng ≥ 0.5 → trả
   "chưa có dữ liệu" mà *không gọi LLM*.
4. Nếu đạt ngưỡng → Gemini trả lời *chỉ dựa trên các đoạn trích được đưa vào*,
   kèm danh sách nguồn nó thực sự dùng → câu trả lời luôn có trích dẫn URL.

### 2.5 Luồng hybrid / so sánh

Cho câu hỏi trộn cả tư vấn lẫn kiến thức ("so sánh UET và HUST về điểm chuẩn
lẫn học phí"):

1. Chạy **song song** hai nhánh: advisory pipeline (nếu cần) và **knowledge
   fan-out** — một query RAG cho từng cặp (trường × chủ đề), vd 2 trường × 2
   chủ đề = 4 query; một query lỗi không làm chết các query còn lại.
2. **Synthesis agent** (LLM) ghép kết quả hai nhánh thành một câu trả lời có
   cấu trúc, với ràng buộc "không thêm thông tin ngoài hai khối dữ liệu";
   LLM lỗi → nối các khối lại một cách deterministic.
3. Nếu hồ sơ chưa đủ để tư vấn: trả lời phần kiến thức ngay, đồng thời hỏi
   tiếp slot còn thiếu.

### 2.6 Inference Gateway — cổng LLM duy nhất

Mọi lời gọi LLM đi qua một gateway với vòng đời thống nhất:

```
caller → registry chọn model theo agent → gọi Gemini (qua key pool)
       → JSON hỏng?  → STRUCTURE_FAILURE → retry cùng model → fallback model khác
       → API lỗi cứng? → InferenceError  → caller tự fallback deterministic
```

- **Registry per-agent**: mỗi tác vụ (trích hồ sơ, QA, OCR, synthesis…) được
  gán model chính/model dự phòng riêng (chủ yếu `gemini-2.5-flash-lite`, nâng
  lên `gemini-2.5-flash` cho QA/synthesis), số lần retry và định dạng output
  (JSON/free-text). Temperature mặc định 0.0 — ưu tiên tính tái lập.
- **Key pool**: nhiều API key Gemini xoay vòng round-robin. Gặp 429/401/403/5xx
  → key đó vào "cooldown" (mặc định 60s hoặc theo `retryDelay` server trả về)
  và thử key kế tiếp; hết key khả dụng mới chịu lỗi.
- **Telemetry** ghi lại từng attempt (agent, model, kết quả, có dùng fallback
  không) phục vụ chẩn đoán.

### 2.7 Tracing — nhìn vào bên trong pipeline

Mỗi node của đồ thị tư vấn được bọc decorator ghi sự kiện vào bảng
`advisory_trace_events`: stage, trạng thái, thời lượng, output JSON rút gọn.
Frontend (khi bật `ADVISORY_DEBUG_UI=1` hoặc `?debug=1`) hiện **panel debug**
poll mỗi 1s, vẽ 6 thẻ stage chuyển pending → running → completed/failed kèm
thời gian, click vào xem output JSON — về cơ bản là cửa sổ quan sát trực tiếp
pipeline đang chạy.

---

## 3. Data — ingestion và luồng dữ liệu

Hệ thống ingest **hai loại dữ liệu** bằng hai pipeline riêng:

| | Structured (tuyển sinh) | Unstructured (kiến thức) |
|---|---|---|
| Nội dung | Chỉ tiêu, phương thức, tổ hợp, điểm chuẩn | Học phí, học bổng, KTX, quy chế… |
| Nguồn | Trang tuyển sinh, đề án PDF, aggregator | Trang web, PDF crawl, văn bản MOET, PDF local |
| Đích | `canonical_admission_records`, `cutoff_records` | `knowledge_chunks` (pgvector) |
| Phục vụ | Advisory pipeline (retrieve/conflict/reason) | Knowledge QA (RAG) |

### 3.1 Pipeline structured: từ URL đến bản ghi canonical

```
Source Registry → Fetch → Route → Parse → Extract → Normalize → Upsert DB
```

1. **Source Registry** — danh mục nguồn theo trường (seed JSON): mỗi nguồn có
   URL, loại (trang chủ TS / đề án PDF / danh sách ngành…), **trust_level
   1–5**, priority, cờ chính thống, và `parser_profile` chỉ định parser nào sẽ
   xử lý nó.
2. **Fetch** — HTTP GET với retry backoff lũy thừa, User-Agent xoay vòng, tính
   SHA-256 nội dung. SSL verify **tắt mặc định** (nhiều site `.gov.vn` hỏng
   cert) — bật lại bằng `ADVISORY_FETCH_VERIFY_SSL`.
3. **Route** — đoán loại tài liệu theo Content-Type → đuôi URL → magic bytes
   (HTML, PDF text, PDF scan…).
4. **Parse** — nếu nguồn có parser chuyên biệt theo trường (VNU-UET homepage,
   VNU-UET đề án PDF, HUST danh sách ngành, HUST thông báo 2026…) thì parser
   đó trích **trực tiếp ra facts**; nếu không, parser generic (BeautifulSoup /
   pdfminer) chỉ trích text + bảng rồi chuyển cho bước extract.
5. **Extract** — regex + nhận diện bảng theo từ khóa cột ("ngành", "mã", "chỉ
   tiêu"…), mỗi fact kèm confidence. Nếu confidence trung bình < 0.6 hoặc
   không trích được gì → **fallback Gemini** trích theo schema JSON (văn bản
   dài được cắt chunk 30KB), rồi merge kết quả hai cách.
6. **Normalize** — quy mọi thứ về canonical bằng **4 từ điển JSON** (programs,
   methods, subjects, combo→method rules), mỗi từ điển có phần `_shared` dùng
   chung + override theo trường:
   - Tên/mã ngành → `program_id` canonical (exact → substring → fuzzy ≥85);
   - Phương thức xét tuyển dạng chữ → mã chuẩn (`thpt_score`,
     `competency_test`…); nếu nguồn không ghi phương thức thì **suy ra từ tổ
     hợp môn** (A00/A01 → điểm thi THPT…);
   - Tổ hợp môn → cấu trúc {mã, môn học}; chỉ tiêu dạng chữ → {giá trị, kiểu
     exact/range/approximate}.
7. **Upsert** — ghi `canonical_admission_records` với khóa **(trường, năm,
   ngành, phương thức, source_url)**. Khóa chứa `source_url` là chủ ý: cùng một
   chương trình từ 2 nguồn tồn tại thành 2 dòng → tầng tư vấn mới có gì để so
   sánh và phát hiện mâu thuẫn. Re-crawl chỉ cập nhật dòng cũ, không nhân đôi.

Dọc đường, dữ liệu trung gian được lưu lại phục vụ audit: `raw_documents`
(bytes gốc + headers) và `extracted_facts` (facts trước chuẩn hóa, kèm
confidence và phương pháp trích).

### 3.2 Điểm chuẩn lịch sử (cutoff) — đường ingest riêng

Điểm chuẩn các năm trước đi đường riêng (`python -m ingestion.ingest_cutoffs`)
với hai chế độ:

- **Seed JSON đã kiểm tay** — validate kiểu *all-or-nothing*: một dòng lỗi là
  báo toàn bộ lỗi và không ghi gì (bảo toàn chất lượng dữ liệu curated).
- **Scrape aggregator** (tuyensinh247 HTML/API) — lỗi dòng nào bỏ dòng đó
  (best-effort).

Khác biệt với bản ghi tuyển sinh: trường phương thức lưu **mã** (không phải tên
hiển thị) và kèm `score_scale` (thang 30 cho điểm THPT, thang 100 cho ĐGTD…) để
tầng reasoning so điểm đúng thang. Đích: bảng `cutoff_records`, cũng upsert
per-source.

### 3.3 Pipeline kiến thức: từ tài liệu đến vector

Bốn đường vào, hội tụ về cùng một flow:

- Registry URL theo trường (`ingestion.knowledge.pipeline --school/--all`);
- Manifest PDF đã crawl và đánh dấu "keep" (`ingest_manifest`);
- Văn bản quy chế quốc gia, gắn scope `MOET` (`ingest_national`);
- Thư mục PDF local (tự phân loại trường/năm bằng LLM đọc trang đầu, có thể
  override bằng file cấu hình).

```
Tài liệu → trích text (hybrid text-layer/OCR) → đánh dấu [Trang N]
        → chunk 1800 ký tự, overlap 256 → embed 768d → knowledge_chunks
```

- **Trích text hybrid**: trang nào có text layer (≥50 ký tự) dùng luôn; trang
  scan được render ảnh ~200 DPI rồi đưa qua **Gemini vision OCR**. Có cơ chế
  phát hiện **OCR thoái hóa** (model lặp vô hạn một ký tự, thường do bảng merge
  cell): output quá dài hoặc >80% là một ký tự → retry với temperature 0.3;
  vẫn hỏng → bỏ trang đó, các trang khác tiếp tục.
- **Chunking** cắt theo ranh giới đoạn/câu (không cắt giữa chừng), mỗi chunk
  giữ metadata (trường, chủ đề, năm, URL nguồn, vị trí ký tự trong tài liệu).
- **Embedding**: `gemini-embedding-001`, 768 chiều, lưu pgvector với chỉ mục
  HNSW (cosine). **Tái sử dụng embedding theo content-hash**: chunk có nội dung
  trùng với bất kỳ chunk nào đã có trong corpus thì lấy lại vector cũ, không
  embed lại — re-ingest gần như miễn phí.
- **Idempotency** hai tầng: tài liệu trùng hash → bỏ qua; chunk upsert theo
  khóa (source_url, vị trí bắt đầu, vị trí kết thúc).

### 3.4 Schema database theo domain

16 migration idempotent (`db/migrations/001–016`, áp dụng tuần tự bởi
`db/setup_db.py`) tạo ra schema chia 4 nhóm:

| Nhóm | Bảng | Vai trò |
|---|---|---|
| **Ingestion structured** | `source_registry`, `discovered_resources`, `raw_documents`, `extracted_facts` | Danh mục nguồn + dấu vết từng bước crawl (audit/lineage) |
| **Canonical store** | `canonical_admission_records`, `cutoff_records` | Sự thật chuẩn hóa, đa dòng per-source, có trust/confidence |
| **Knowledge (RAG)** | `knowledge_documents`, `knowledge_chunks` (vector 768 + HNSW), `program_catalog_embeddings` | Corpus RAG + embedding tên ngành cho major resolver |
| **Chat & vận hành** | `chat_sessions` (hồ sơ JSONB), `chat_messages`, `chat_advisory_runs`, `advisory_trace_events` | Phiên, transcript, run nền và trace từng stage |

Luồng dữ liệu tổng quát qua các bảng:

```
source_registry → raw_documents → extracted_facts → canonical_admission_records ─┐
                                                       cutoff_records ───────────┤→ advisory pipeline
knowledge_documents → knowledge_chunks ──────────────────────────────────────────┘→ knowledge QA
chat_sessions/messages ⇄ chat services → chat_advisory_runs → advisory_trace_events
```

---

## 4. Các cơ chế nền tảng khác

**Suy giảm có kiểm soát ở mọi điểm gọi LLM.** Bảng fallback tiêu biểu:

| Điểm gọi LLM | Khi LLM lỗi |
|---|---|
| Phân loại intent | Bộ phân loại từ khóa tiếng Việt không dấu |
| Trích hồ sơ | Regex + từ điển alias |
| Phân xử mâu thuẫn quota | Đánh dấu "chưa giải quyết", hạ band gợi ý |
| Knowledge QA | Trả "chưa có dữ liệu" (không bịa) |
| Synthesis hybrid | Nối các khối kết quả deterministic |
| OCR trang PDF | Bỏ trang lỗi, tiếp tục các trang khác |

**Cô lập database khi test.** `pytest` tự động chuyển mọi kết nối sang database
`admission_test` (tạo + migrate tự động) trước khi chạy, khôi phục sau khi
xong — các fixture có TRUNCATE không bao giờ đụng vào dữ liệu dev trong
`admission`.

**Mock dữ liệu mâu thuẫn.** Đặt `ADVISORY_MOCK_CONFLICTS=1` để node retrieve
trả về bộ ứng viên giả có quota mâu thuẫn sẵn — test luồng xử lý conflict mà
không cần dựng dữ liệu thật.

**Console UTF-8 trên Windows.** Các CLI ingestion tự cấu hình lại stdout/stderr
sang UTF-8 trước khi chạy để tên ngành tiếng Việt không vỡ trên console Windows.

**Frontend tối giản, không framework.** Vanilla JS chia module (messages,
trace, theme, typewriter, toasts…), markdown render bằng marked.js, trạng thái
phiên trong localStorage. Realtime bằng polling thay vì WebSocket — chấp nhận
trễ ~1s đổi lấy backend không phải quản lý kết nối.

**Điểm cần biết khi vận hành:**
- Run nền không có timeout cứng — nếu một lời gọi LLM treo, worker thread (tối
  đa 2) bị giữ; phía client chỉ thấy phiên kẹt ở `running`.
- Telemetry inference hiện chỉ ở bộ nhớ tiến trình, chưa ghi DB.
- Đổi `EMBEDDING_DIM` đòi hỏi migrate cột vector và re-embed toàn bộ corpus.

---

## 5. Bản đồ entry point

| Việc cần làm | Lệnh |
|---|---|
| Dựng DB (Docker) + migrate + seed | `docker compose up -d --wait db` rồi `python -m db.setup_db` |
| Ingest dữ liệu tuyển sinh một trường | `python -m ingestion.main --school hust` |
| Ingest điểm chuẩn lịch sử | `python -m ingestion.ingest_cutoffs --seed` |
| Ingest kho kiến thức | `python -m ingestion.knowledge.pipeline --all` (+ `ingest_manifest`, `ingest_national`) |
| Kiểm tra corpus RAG | `python -m ingestion.knowledge.verify_corpus` |
| Chạy web app | `python -m uvicorn web.app:app --reload` |
| Demo advisory qua CLI (không cần web) | `python main.py --query "..."` |
| Test (tự cô lập sang `admission_test`) | `python -m pytest -q` |
