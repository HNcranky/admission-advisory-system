# Báo cáo Audit Kiến trúc & Tái cấu trúc — Admission Advisory System

> Ngày: 2026-06-16 · Phạm vi: toàn repo (loại trừ `.venv`, `.git`, `__pycache__`,
> `latex*/`). Phương pháp: 6 agent điều tra song song, đối chiếu bằng `git grep` /
> đọc file. **Không thay đổi code** — đây là báo cáo đánh giá có evidence.

## Tóm tắt điều hành

Codebase **nhìn chung khỏe mạnh**: Pydantic v2 đồng nhất, không có mutable default
argument, không có `except:` trần, pattern repository (`connection_factory` +
`_cursor`) được áp dụng đúng ở phần lớn `services/`, không có secret hardcode,
không có SQL injection trên data path, không có deserialize không an toàn. Test
suite (~15k LOC) dùng `monkeypatch`/fake thay vì mock bừa — tốt hơn mặt bằng chung.

Tuy vậy có một số **vấn đề thật, đáng sửa**, xếp theo mức độ ưu tiên:

| # | Vấn đề | Mức | Nhóm |
|---|--------|-----|------|
| 1 | LLM call (Gemini) **không có timeout** → nghẽn worker pool | Cao | Bảo mật/Scale |
| 2 | `llm_extractor.py` **bỏ qua inference gateway**, dùng SDK cũ, không xoay key | Cao | Trùng lặp/Vận hành |
| 3 | Job state nằm **in-process** (ThreadPoolExecutor) → không scale ngang, mất run khi restart | Cao | Scale |
| 4 | **Không connection pooling** — mỗi call mở 1 connection mới | Cao | Scale |
| 5 | 5 bản chuẩn hóa tiếng Việt (fold dấu) **lệch nhau ở xử lý `đ`** → rủi ro matching sai | Cao | Trùng lặp/Đúng đắn |
| 6 | `db_writer` **nuốt exception**, trả về count → che mất data-loss | Cao | Đúng đắn |
| 7 | Dead code: nhiều file/hàm/bảng không dùng | Trung bình | Dead code |
| 8 | `agents/models.py` (domain models) bị đặt sai tầng → services import lên agents | Trung bình | Kiến trúc |
| 9 | Routes FastAPI sync + I/O LLM blocking inline trong request | Trung bình | Scale |
| 10 | 5 dependency thừa (`langchain`, `httpx`, `tenacity`, `certifi`, `python-dateutil`) | Thấp | Deps |

---

## 1. Dead code & thành phần không dùng

Bằng chứng: "0 refs" nghĩa là `git grep` chỉ thấy đúng định nghĩa, không có nơi gọi.

### File chết hoàn toàn (confidence: CAO)
- `ingestion/models/admission_schema.py` — `AdmissionMethod`/`ProgramAdmission`/`AdmissionDocument`
  không được import ở đâu. Khái niệm này đã được mô hình hóa đầy đủ hơn bởi
  `ExtractedAdmissionFact`/`NormalizedAdmissionRecord` trong `pipeline_models.py`.
  → **Xóa.** Rủi ro: rất thấp.
- `services/inference/providers/base.py` — `BaseInferenceProvider(ABC)` không có
  consumer; `GeminiProvider` **không** kế thừa nó. → Xóa, hoặc nối `GeminiProvider`
  vào ABC nếu thực sự muốn đa provider (xem §4 mục 8).
- `services/chat/profile_state_service.py` — chỉ được import bởi chính test của nó.
  `parse_pending_slot_answer` (0 refs, chết hẳn); `merge_profile_state` ghi docstring
  "DEPRECATED khỏi conversation flow", chỉ test gọi. → Xóa module + test, hoặc tối
  thiểu bỏ `parse_pending_slot_answer`.

### Hàm/class chết — 0 refs toàn repo (confidence: CAO)
| Symbol | Vị trí |
|--------|--------|
| `save_raw_document`, `save_extracted_facts`, `load_and_save_from_json`, `psycopg2_Binary` | `ingestion/storage/db_writer.py:31/83/226/75` |
| `parse_hust_programs` ("Legacy entry point") | `ingestion/parsers/hust_program_parser.py:719` |
| `run_ingestion` ("Legacy entry point") | `ingestion/pipeline/ingestion_pipeline.py:263` |
| `AdvisoryRunRecord` | `services/chat/models.py:64` |
| `index_candidates_by_id` | `services/reasoning_service.py:251` |
| `detect_conflicts` (logic thật nằm ở `services/conflict/`) | `services/retrieval_service.py:221` |

Pipeline ghi thật chỉ đi qua `save_canonical_records` / `save_cutoff_records`.

### Đường dữ liệu chết (confidence: TRUNG BÌNH — cần quyết định, không xóa mù)
- Bảng `raw_documents` và `extracted_facts` chỉ được **ghi** bởi các hàm `db_writer`
  đã chết ở trên ⇒ thực tế **không bao giờ được populate**. Nhưng
  `services/conflict/evidence_agent.py:31-32` lại `LEFT JOIN extracted_facts` và
  `raw_documents` ⇒ join này luôn ra NULL ở production. Cần quyết định: hoặc bật
  lại đường ghi facts, hoặc đơn giản hóa query evidence.

### Bảng DB không dùng (confidence: CAO)
- `discovered_resources` (migration `002`) — chỉ xuất hiện trong danh sách kiểm tra
  tồn-tại của `db/setup_db.py:103`. Không có INSERT/SELECT/UPDATE nào. → Tính năng
  crawler-discovery dự kiến nhưng chưa nối. Cân nhắc drop (cần phối hợp vì là migration).

### Routes — KHÔNG có route chết
6 routes đều được gọi từ JS/template; `/health` không có caller JS nhưng là endpoint
ops chuẩn, có test phủ. → Giữ.

### Scripts mồ côi (confidence: TRUNG BÌNH)
`scripts/` là probe one-off theo chủ đích (CLAUDE.md). Mồ côi nhất (không ref ở code
lẫn docs): `_probe_hust_coverage.py`, `_probe_hust_full_pipeline.py`,
`_probe_hust_pairs.py`. Xóa được nếu dọn `scripts/`.

---

## 2. Trùng lặp & module chồng chéo

| # | Trùng lặp | Tác động | Conf. |
|---|-----------|----------|-------|
| 2.1 | `llm_extractor.py` dùng SDK `google.generativeai` **cũ** trực tiếp, tự strip ```` ``` ````-fence + `json.loads`, **không xoay key / không telemetry / không fallback** — vi phạm quy ước "mọi LLM call qua `build_default_gateway()`" | CAO | CAO |
| 2.2 | Fold dấu tiếng Việt 5 bản **lệch nhau ở `đ`** (xem dưới) | Cao | CAO |
| 2.3 | `_cursor` context manager copy-paste 5 lần | TB | CAO |
| 2.4 | Scaffold load JSON dictionary (`_*_CACHE` + `_load_all` + `_load_dict`) lặp ở 4 mapper | TB | CAO |
| 2.5 | `RunDispatcher` vs `HybridDispatcher` gần như giống hệt (kể cả `_mark_failed`) | TB | TB |
| 2.6 | Factory connection DB 3 hàm giống hệt + inline 5 lần trong `setup_db.py` | Thấp-TB | CAO |
| 2.7 | `_vector_literal` (pgvector) trùng 2 nơi | Thấp | CAO |
| 2.8 | `_dedupe`/dedupe-preserve-order: 4 bản đặt tên + ~8 bản inline | Thấp | CAO |

**Chi tiết 2.2 (quan trọng — rủi ro đúng đắn):** routine "bỏ dấu, lowercase, gộp
khoảng trắng" được viết lại 5 lần và **không nhất quán**:
- `services/profile_service.py:41` `normalize_text` — map `đ→d` rồi NFKD + ascii-strip.
- `ingestion/parsers/vnu_uet_admission_parser.py:52` `_normalize` — NFKD + `translate({Đ:D, đ:d})`.
- `ingestion/parsers/hust_program_parser.py:75` `_normalize_for_match` — **không xử lý `đ`** ⇒ "đ" sống sót, matching sai.
- `ingestion/main.py:208` — NFKD + ascii-strip, **không pre-map `đ`** ⇒ rụng luôn `đ`.

→ Nguồn chân lý: `profile_service.normalize_text` (xử lý `đ` đúng nhất). Trích thành
1 util `vietnamese_fold(text)` duy nhất, định tuyến cả 5 nơi qua đó.

**Nguồn chân lý các mục khác:** gom `_cursor` + factory connection + `_vector_literal`
vào 1 module `services/db/` dùng chung; mục 2.1 migrate `llm_extract` sang
`build_default_gateway().run(...)` (đồng thời gỡ luôn dependency vào package
`google-generativeai` cũ).

**Tái dụng lành mạnh (KHÔNG cần sửa):** call-site gateway dùng `gateway.run(...)` +
`except InferenceError` đồng nhất; `eval/knowledge_qa/gateways.py` compose gateway
đúng cách; parser theo từng trường là chuyên biệt hợp lệ (chỉ trích phần fold/dedupe).

---

## 3. Chất lượng code & readability

Tổng thể tốt. Các "tội đồ" thật:

**Style/PEP8**
- **(CAO) Nuốt lỗi ở storage** — `ingestion/storage/db_writer.py`: `save_extracted_facts`
  (L94), `save_canonical_records` (L146), `save_cutoff_records` (L255) bắt `except
  Exception`, log rồi **return count/ids**. Caller không phân biệt được "0 record" với
  "DB lỗi". `save_cutoff_records` thậm chí dùng count làm exit code ⇒ lỗi DB trông như
  "không có gì để lưu". → Để exception nổi lên (context manager đã rollback) hoặc trả
  cờ success/failure tường minh. **Đây là finding duy nhất có tác động data-integrity.**
- (Thấp) Dòng whitespace-only do bị xóa `#` của divider cũ: `db_writer.py` (1,29,81,132,224),
  `hust_program_parser.py` (1,34,163,188...), `ingestion_pipeline.py` (1,74,83,88,94). → Xóa.
- (Thấp) Import giữa file: `services/chat/intent_router.py:31` import sau hàm/hằng. → Đưa lên đầu.
- (Thấp) `psycopg2_Binary` import `psycopg2` trong hàm, gọi mỗi row + tên sai snake_case.
- (Thấp) `services/chat/conversation_service.py`: ~12 method `_handle_*` thiếu type annotation.

**Naming** — không có module grab-bag (`manager`/`utils`/`processor`); tên `*_service`
/`*_dispatcher`/`*_router` đều map 1 trách nhiệm rõ. Vài tên terse: `n` →
`recommendation_count` (`explanation_service.py:139`).

**Comments** — phần lớn comment **giá trị cao, nên giữ** (business rule, ghi chú sự
cố session-131 ở `intent_router.py:170`, nhãn "Ngả 1/2/3"). Chỉ bỏ comment `# Step N`
trùng với `logger.info("Step N")` ngay dưới (`ingestion_pipeline.py`).

**Complexity (god-method / hàm dài)**
- (CAO) `HustProgramParser._parse_card` (`hust_program_parser.py:423-592`, ~120 dòng):
  trộn parse + network I/O + dựng record. → Tách `_extract_header/_extract_combos/
  _extract_methods/_build_conditions/_build_fact` (đã có ranh giới comment sẵn).
- (CAO) `_extract_tuition_value` (`hust_program_parser.py:126-199`, 92 dòng, 4 chiến
  lược fallback lặp cùng regex 3×). → Trích `_tuition_from_text(text)`.
- (TB) `reason_candidates` (`reasoning_service.py:120-248`, ~128 dòng, lồng 4-5 tầng):
  3 "Ngả" là 3 chiến lược chấm điểm tách biệt → tách `_score_by_combination/
  _score_by_cutoff/_resolve_band`.
- (TB) `ConversationService` (477 dòng, 13 method): `handle_user_message` route-dispatch
  thủ công ×7 → bảng `route → handler`.

---

## 4. Kiến trúc & phụ thuộc

Tầng dự kiến: `web → graph/agents → services → ingestion(config/storage)`. Không có
import cycle thật (Python sẽ crash), nhưng có 1 đảo chiều cấu trúc + vài near-cycle.

1. **(CAO) `services/` import `agents/`** — `agents/models.py` là domain models thật
   (`CandidateProgram`, `StudentProfile`...) nhưng bị đặt ở tầng orchestration. 12
   service + `state.py` đều `from agents.models import ...`. → **Move `agents/models.py`
   → `domain/models.py`** (để lại shim re-export). Cơ học, lật ~13 cạnh về 1 leaf package.
2. **(CAO) `BaseInferenceProvider` chết** (xem §1) — ABC ngụ ý pluggable nhưng gateway
   hardcode key `"gemini"` (`gateway.py:8,13,19,36`). → Hoặc inline (chấp nhận Gemini-only),
   hoặc làm thật: `GeminiProvider(BaseInferenceProvider)` + gateway resolve theo
   `policy.primary_model`. Chọn 1; hiện tại "lửng lơ".
3. **(TB) `mock_retrieval.py` single-consumer** — chỉ `retrieval_service.py` dùng. → Inline.
4. **(TB) `reasoning_service` import private của `explanation_service`** (`_fmt_num`,
   `_program_label`). → Trích ra `services/formatting.py` (2 consumer ⇒ abstraction chính đáng).
5. **(TB) services reach thẳng vào `ingestion.storage.db_connection`** —
   `conflict/evidence_agent.py`, `retrieval_service.py`, `profile/major_catalog*` tự viết
   SQL, bỏ qua pattern repository. → Tạo `ConflictEvidenceRepository`/`CutoffRepository`
   nhận `connection_factory`, dời SQL vào (không viết lại query).
6. **(TB) Logic orchestration trong transport** — `web/routes/chat_api.py:48-74`
   (`post_message`) tự gọi `repo.create_run/count_runs`, tính `closing_seed`, chọn
   dispatcher. → Đưa thành `ConversationService.start_run(...)`; route chỉ validate + delegate.
7. **(TB, thấp) Singleton import-time** — `agent_tracer.py:10` `_default_repo =
   TraceRepository()` chạy lúc import (an toàn vì không mở connection). → Lazy-init cho nhất quán.
8. **(TB) Near-cycle `ingestion ↔ services`** vá bằng import trong hàm
   (`knowledge/crawl.py:43`, `local_metadata.py:126`, `pdf_ocr.py:138`...). Mảnh chung
   là embedder + key_pool. → **Move `GeminiEmbedder` (`ingestion/knowledge/embedder.py`)
   sang `services/inference/`** (nó đã phụ thuộc `key_pool`), gỡ back-edge mạnh nhất.

**Lành mạnh (đối chứng):** layering nội bộ `ingestion/` sạch & acyclic;
`BaseSpecializedParser`+`ParserRegistry` là abstraction tốt với 4 implementation;
env var tập trung ở `settings.py`; `web/app.py` là composition root chuẩn.

---

## 5. Scalability & hiệu năng (không đề xuất viết lại)

**Data layer**
- **(D1, CAO) Không connection pooling** — mỗi method repository mở connection mới rồi
  `close()`. 1 lượt chat = hàng chục connect/teardown. Bùng tải → cạn `max_connections`.
  → `psycopg2.pool.ThreadedConnectionPool` (hoặc pgbouncer) sau `connection_factory`.
- **(D2, TB — chỉ ingestion) Insert từng row** (`db_writer.py:96/148/257`). → `execute_values`.
- **(D3, TB) `save_extracted_facts` không `ON CONFLICT`** ⇒ non-idempotent, re-ingest nhân đôi
  (các writer khác đã idempotent). → thêm UNIQUE + UPSERT, hoặc delete-by-`raw_document_id`.
- **(D4, thấp) Thiếu index** trên `knowledge_chunks(knowledge_document_id)` (filter ở
  `repository.py:118-119,151`). → `CREATE INDEX`. Phần index còn lại đầy đủ (HNSW vector OK).
- **(D5, TB) List không phân trang** — `list_message`/`list_events_for_run` `fetchall()`
  không LIMIT; mỗi `handle_user_message` fetch lại toàn bộ history. → cap/paginate.

**App layer**
- **(A1, CAO) Routes sync + LLM I/O blocking inline** — mọi route là `def`; `POST /messages`
  chạy intent-router + profile-extract LLM **đồng bộ trong request**, giữ worker threadpool
  (mặc định 40) suốt round-trip LLM. → tách LLM khỏi request hoặc chỉnh threadpool cẩn thận.
- **(A2, CAO) LLM call không timeout** — `gemini_provider.py:61` `generate_content(...)`
  và `embedder.py:46` `embed_content(...)` không truyền timeout. Connection treo ⇒ block
  worker (chỉ 2!) vô hạn, rotation key không bao giờ kích hoạt. → truyền `http_options`/timeout.
- **(A3, CAO) ThreadPoolExecutor chỉ 2 worker, queue không chặn, fire-and-forget** —
  run thứ 3+ xếp hàng vô hình; restart ⇒ mất run, session kẹt `running` mãi (recovery
  `_mark_failed` chỉ chạy khi có exception, không cho item bị drop). → chặn queue/reject,
  size worker theo tải, persist run (xem S1).
- **(A4, TB) Không cache LLM/embedding** — `build_default_gateway()` dựng lại mỗi request;
  cùng câu hỏi vẫn re-embed (đốt quota free-tier 20 req/ngày). → LRU/content-hash cache trên `embed_query`.

**System design**
- **(S1, CAO) Job state in-process** — run chỉ sống trong executor; DB đánh `running` nhưng
  thực thi in-memory ⇒ không scale ngang (replica A không thấy job của B), restart = mất.
  → queue bền (bảng DB poll/claim — `chat_advisory_runs` đã có `status`/`started_at`, hoặc Redis/Celery).
- **(S2, TB) Cooldown key-pool per-process** — đa replica mỗi cái 1 view ⇒ tiêu lố ngân sách 429.
  → shared store (Redis) nếu >1 replica.
- **(S3, thấp) Backoff fetch không jitter** (`http_fetcher.py:103`). → thêm jitter.

Không tìm thấy N+1 trên request read-path; chỉ có loop ghi batch (D2).

---

## 6. Dependency cleanup

**Gỡ được (0 hit trong code):**
- `langchain` — chỉ `langgraph` được dùng; `langchain` là package riêng, chết.
- `httpx` — mọi HTTP qua `requests`; httpx chỉ là transitive của TestClient.
- `tenacity` — retry đều tự viết tay (`http_fetcher`, `key_pool`).
- `certifi` — `requests` đã kéo transitive; không dùng `certifi.where()` trực tiếp.
- `python-dateutil` — code dùng `datetime` stdlib; không import `dateutil`.

**Giữ nhưng chồng chéo:** 3 lib PDF cùng tồn tại — `pdfminer.six` (text thuần),
`pdfplumber` (text+table, vốn phụ thuộc pdfminer), `pymupdf` (render trang→PNG cho OCR).
`pdf_parser.py` dùng pdfminer trực tiếp **có thể** chuyển sang pdfplumber để bỏ
dependency trực tiếp vào pdfminer — là refactor, không phải xóa sạch.

---

## 7. Chất lượng test & vùng refactor không an toàn

Suite khỏe (chỉ 4 `MagicMock`; cô lập bằng `monkeypatch`/fake). Integration được gate
sạch (skip nếu không có Docker DB).

**Module logic quan trọng nhưng KHÔNG có test (⇒ refactor KHÔNG an toàn):**
`ingestion/normalization/normalizer.py` (trái tim raw→canonical),
`quota_parser.py`, `method_mapper.py`, `combo_method_mapper.py`,
`subject_combination_mapper.py`, `extractors/admission_extractor.py`,
`extractors/llm_extractor.py`, `parsers/hust_program_parser.py` (732 dòng, module lớn
nhất không test), `pdf_parser.py`, `router/document_router.py`, `parser_dispatcher.py`,
`fetch_dispatcher.py`. Orchestrator `ingestion_pipeline.py` cũng không test trực tiếp.

→ **Trước khi refactor `hust_program_parser` (§3) hay chuỗi parse→extract→normalize,
cần viết test characterization** (đặc biệt §2.2 fold dấu, §3 tách `_parse_card`).
`reason_candidates` thì AN TOÀN — đã được phủ gián tiếp qua `test_reasoning_agent.py`.

**Gap:** chưa có integration test cho chuỗi parse→extract→normalize (chỉ phủ phần đuôi
db-writer). Overlap nhẹ: `test_retrieval_service.py` vs `test_mock_retrieval.py`.

---

## 8. Bảo mật & robustness

Sạch ở các điểm lớn: không secret hardcode (`.env` gitignored, không tracked), không
SQL injection trên data path (f-string chỉ nội suy hằng cột tĩnh, value đi qua `%s`
psycopg2), không `eval/exec/pickle/yaml.load`, không `except:` trần, không rò resource.

| # | Phát hiện | Vị trí | Mức |
|---|-----------|--------|-----|
| C1 | **LLM call không timeout** (trùng A2) → treo worker pool | `gemini_provider.py:61-65` | Cao-TB |
| C2 | **Không giới hạn độ dài message** — `ChatMessageCreate.content` không `max_length`, endpoint public ẩn danh → DoS/đốt token | `web/routes/chat_api.py:16` | TB |
| C3 | **SSL verify tắt mặc định** (`ADVISORY_FETCH_VERIFY_SSL=false`) — chủ đích vì cert `.gov.vn` hỏng, có log, nhưng là phơi nhiễm MITM mặc định | `settings.py:95`; `http_fetcher.py:67` | TB (chủ đích) |
| C4 | **DB password fallback `postgres`** — ổn cho dev, đảm bảo prod luôn set `DB_PASSWORD` | `settings.py:40` | Thấp |
| C5 | f-string trong SQL — **KHÔNG injectable** (chỉ nội suy hằng nội bộ, script DDL) | `verify_db.py:7`, `setup_db.py:42` | Info |

→ Ưu tiên: C1 (thêm timeout), C2 (`Field(max_length=...)`), C3 (cân nhắc bật mặc định
`true` + opt-out theo source, hoặc document rủi ro còn lại).

---

## 9. Lộ trình tái cấu trúc (P0 → P3)

Nguyên tắc: PR nhỏ, review được; ưu tiên **xóa hơn dời**, **đơn giản hóa hơn trừu tượng hóa**.

### P0 — Dọn an toàn (rủi ro rất thấp, không đổi hành vi)
| Hạng mục | Giá trị | Rủi ro | ~Files | Cỡ PR | Test |
|----------|---------|--------|--------|-------|------|
| Xóa file/hàm chết (§1: `admission_schema.py`, `providers/base.py`, các hàm `db_writer` chết, `parse_hust_programs`, `run_ingestion`, `AdvisoryRunRecord`, `index_candidates_by_id`, `detect_conflicts`) | Giảm nhiễu, giảm bề mặt bảo trì | Rất thấp | ~8 | S | chạy pytest hiện có |
| Xóa dòng whitespace divider chết + đưa import `intent_router` lên đầu (§3) | Sạch lint | Rất thấp | ~5 | XS | lint + pytest |
| Bỏ 5 dependency thừa khỏi `requirements.txt` (§6) | Giảm build/CVE surface | Thấp | 1 | XS | cài lại + pytest + smoke import |
| Đổi tên `psycopg2_Binary`→`_to_db_binary`, hoist import (§3) | snake_case | Rất thấp | 1 | XS | pytest |

### P1 — Cải thiện rủi ro thấp (trích trùng lặp, siết test)
| Hạng mục | Giá trị | Rủi ro | ~Files | Cỡ PR | Test |
|----------|---------|--------|--------|-------|------|
| **(ưu tiên đầu) Thêm timeout LLM call** (A2/C1) | Chặn nghẽn worker pool | Thấp | 2 | XS | unit + giả lập treo |
| Thêm `max_length` cho `ChatMessageCreate.content` (C2) | Chống DoS endpoint public | Thấp | 1 | XS | test biên |
| Gom 1 util `vietnamese_fold()`, route 5 nơi qua đó (§2.2) — **viết test characterization trước** | Sửa lệch `đ`, hết drift | TB (cần test trước) | ~5 | M | test fold + parser HUST |
| Gom `_cursor`+factory connection+`_vector_literal` vào `services/db/` (§2.3/2.6/2.7) | -50 dòng, 1 nơi sửa transaction | Thấp | ~8 | M | test repository hiện có |
| Trích `services/formatting.py` cho `_fmt_num`/`_program_label` (§4.4) | Bỏ coupling private | Thấp | 3 | S | pytest |
| Đặt `extracted_facts` idempotent (D3) | Hết nhân đôi khi re-ingest | Thấp | 1+migration | S | integration db |
| Thêm index `knowledge_chunks(knowledge_document_id)` (D4) | Tránh seq-scan | Rất thấp | 1 migration | XS | — |
| Viết test characterization cho normalizer/mapper/extractor (§7) | Mở khóa refactor an toàn | Thấp | ~6 test | M | tự là test |

### P2 — Kiến trúc rủi ro trung bình
| Hạng mục | Giá trị | Rủi ro | ~Files | Cỡ PR | Test |
|----------|---------|--------|--------|-------|------|
| **Migrate `llm_extractor` sang inference gateway** (§2.1) — gỡ SDK cũ, có xoay key/telemetry/fallback | Resilience + đúng quy ước + gỡ dep `google-generativeai` | TB | ~3 | M | test extractor (mới) + FakeGateway |
| Move `agents/models.py`→`domain/models.py` + shim (§4.1) | Sửa đảo chiều tầng | TB (cơ học, ~13 import) | ~14 | M | pytest toàn bộ |
| Move `GeminiEmbedder`→`services/inference/`, biến import-trong-hàm thành top-level (§4.8) | Gỡ back-edge `ingestion↔services` | TB | ~6 | M | pytest |
| Tách `_parse_card`/`_extract_tuition_value` (§3) — **cần test §7 trước** | Dễ bảo trì parser lớn nhất | TB | 1 | M | characterization HUST |
| Đưa orchestration ra khỏi `chat_api.post_message` → `start_run()` (§4.6) | Transport mỏng, đúng tầng | TB | 2 | S | test web + service |
| Repository cho conflict/cutoff SQL (§4.5) | Theo pattern, gỡ coupling ingestion | TB | ~4 | M | test repo (mới) |
| `BaseRunDispatcher` gộp Run/Hybrid dispatcher (§2.5) | Bớt copy-paste, sửa message lệch dấu | TB | ~3 | S | test dispatcher |
| Quyết định `discovered_resources` + đường `raw_documents/extracted_facts` (§1) | Bỏ schema/đường chết hoặc nối lại | TB | 1-2 | S | review thủ công |

### P3 — Tái thiết kiến trúc lớn (scale)
| Hạng mục | Giá trị | Rủi ro | ~Files | Cỡ PR | Test |
|----------|---------|--------|--------|-------|------|
| **Queue bền cho advisory run** (S1/A3) — bảng claim-based hoặc Redis/Celery | Scale ngang, không mất run khi restart | Cao | ~6 | L | integration + chaos restart |
| **Connection pooling** (D1) — `ThreadedConnectionPool`/pgbouncer sau factory | Chịu tải đồng thời | TB-Cao | ~5 | M | load test |
| Chuyển LLM I/O ra khỏi request path / async hóa routes (A1) | Hết bão hòa threadpool | Cao | ~4 | L | load test |
| Shared cooldown key-pool (S2) + cache embedding/intent (A4) | Tiết kiệm quota đa replica | TB | ~3 | M | unit + đo quota |

---

## Phụ lục — Khuyến nghị thứ tự thực thi

1. **Tuần 1 (P0 + 2 quick-win P1):** xóa dead code, gỡ dep thừa, **thêm timeout LLM**,
   `max_length` message. Toàn bộ rủi ro rất thấp, lợi ích tức thì.
2. **Tuần 2-3 (P1):** viết test characterization (normalizer/mapper/parser) → rồi gom
   `vietnamese_fold` và `services/db/`. Idempotent `extracted_facts` + index.
3. **Sprint sau (P2):** migrate `llm_extractor` qua gateway (giá trị cao nhất nhóm
   trùng lặp), move domain models, tách parser lớn.
4. **Khi cần scale thật (P3):** queue bền + connection pooling trước, async hóa sau.

> Mỗi mục là 1 PR độc lập, có chiến lược test riêng. Không mục nào yêu cầu viết lại hệ
> thống; tất cả bảo toàn hành vi hiện tại.
