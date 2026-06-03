# Thiết kế: Đưa PDF scan vào luồng knowledge embedding (OCR qua Gemini vision)

- **Ngày:** 2026-06-04
- **Trạng thái:** Draft (chờ review)
- **Phạm vi:** Knowledge/RAG ingestion (`ingestion/knowledge/`), inference gateway (`services/inference/`), knowledge retrieval (`services/knowledge/repository.py`)
- **Động lực gốc:** Cần làm giàu knowledge corpus từ ~<50 PDF chính thức dạng **scan** (ảnh, không có text layer). Luồng hiện tại làm các file này "lặng lẽ biến mất".

---

## 1. Bối cảnh & vấn đề

Luồng knowledge hiện tại (`ingestion/knowledge/pipeline.py`):

```
http_fetch(source_url) → extract_pages (pdfplumber.extract_text)
  → pages_to_marked_text → split_into_chunks → GeminiEmbedder → pgvector
```

Hai điểm vỡ với PDF scan:

1. **OCR không tồn tại.** `pdfplumber.page.extract_text()` (`ingestion/knowledge/pdf_pages.py:14`)
   trả `""` cho trang ảnh → `pages_to_marked_text` bỏ mọi trang rỗng → **0 chunk, 0 embedding,
   không lỗi, không cảnh báo**. Bộ phát hiện scan sẵn có (`document_router._refine_pdf_type`)
   chỉ nằm ở pipeline admission, không nối vào knowledge, và kể cả khi phát hiện cũng
   không có handler OCR.
2. **Mọi tài liệu phải đăng ký tay** qua `knowledge_sources.json` (URL-based) — không có
   đường ingest file local, và mỗi lần thêm tài liệu phải sửa JSON.

Ràng buộc đã chốt với người dùng:
- Quy mô: **ít, một lần** (<~50 file), tài liệu chính thức tiếng Việt.
- Nội dung: **hỗn hợp prose + bảng** trong cùng tài liệu.
- Nguồn: **file local**, người dùng muốn tách 2 folder `pdf_text/` và `pdf_scanned/`
  để thống nhất đầu vào, và **không phải đăng ký từng file**.

## 2. Mục tiêu / Ngoài phạm vi

**Mục tiêu**
- G1. PDF scan được OCR thành text (bảng giữ dạng markdown) và embed vào pgvector
  **không đổi** phần chunker/embedder/dedup sẵn có.
- G2. Thả file vào folder → chạy 1 lệnh → xong. **Không đăng ký** từng file vào JSON nào.
- G3. PDF "lai" (vài trang text, vài trang scan) xử lý đúng từng trang.
- G4. Không bao giờ "lặng lẽ biến mất" nữa: mọi trang fail/độ nhớt thấp phải được
  cảnh báo rõ trong summary.
- G5. Mọi LLM call đi qua `build_default_gateway()` (đúng convention repo), degrade
  gracefully khi `InferenceError`.
- G6. Idempotent: file không đổi → re-run không OCR lại, không embed lại.

**Ngoài phạm vi**
- Nguồn web/URL: `knowledge_sources.json` + luồng fetch hiện tại **giữ nguyên**.
- Cache OCR theo trang (page-image hash) — YAGNI ở quy mô <50 file; ghi nhận làm sau
  nếu quy mô tăng.
- Topic per-chunk classification — YAGNI (xem mục 6).
- Script sort file tự động — bỏ (auto-discovery + hybrid extractor đã phủ).
- Đổ dữ liệu bảng vào canonical store (structured) — việc của pipeline admission, không
  thuộc luồng knowledge này.

## 3. Quyết định kiến trúc (đã chốt qua brainstorm)

| # | Quyết định | Lý do |
|---|---|---|
| D1 | OCR engine = **Gemini vision** qua gateway sẵn có | Chất lượng tiếng Việt + bảng tốt nhất; tái dùng key-pool/retry/fallback/telemetry; <50 file → chi phí không đáng kể. Tesseract kém bảng + cần binary hệ thống; Document AI thừa cho quy mô này. |
| D2 | **Hybrid theo trang**: trang có text layer ≥ ngưỡng → dùng pdfplumber; trang ảnh → render + OCR | Xử lý PDF lai; trang text thật không tốn call OCR nào. |
| D3 | Folder = **ý định, không phải lệnh**: cả 2 folder chạy cùng extractor hybrid; lệch thực tế → WARNING | Ép cứng theo folder thì file bỏ nhầm chỗ tái diễn bug "lặng lẽ mất nội dung". |
| D4 | **Auto-discovery, miễn đăng ký**: quét đệ quy 2 folder, metadata tự suy | Yêu cầu trực tiếp của người dùng (G2). |
| D5 | LLM classify chỉ **`{school, year}`** từ text trang 1–2 | `school` là hard filter trong `vector_search` — bắt buộc đúng. `topic`/`document_type` không cần (xem mục 6). |
| D6 | `topic = NULL` cho PDF local + sửa `vector_search`: `AND (topic = %s OR topic IS NULL)` | PDF chính thức đa chủ đề; gán 1 topic/file rồi lọc cứng sẽ làm nội dung vô hình với phần lớn câu hỏi. NULL = wildcard; web source giữ nguyên hành vi. |
| D7 | `document_type` = tên folder (`pdf_text` / `pdf_scanned`) | Không được dùng trong retrieval; lấy từ folder là miễn phí và tiện debug chất lượng OCR. |
| D8 | Render trang bằng **PyMuPDF** (`pymupdf`), ~200 DPI PNG | Pip-only, không cần poppler — thân thiện Windows. |

## 4. Kiến trúc & data flow

```
data/knowledge/                          ← gitignore (không commit tài liệu)
├── pdf_text/                            ← PDF có text layer
├── pdf_scanned/                         ← PDF scan
└── overrides.json                       ← (tuỳ chọn) sửa metadata khi classify nhầm

python -m ingestion.knowledge.pipeline --local-dir data/knowledge
        │
        ▼
KnowledgePipeline.run_for_local_dir()            [MỚI]
  │  quét đệ quy *.pdf trong 2 folder
  │  đọc bytes, content_hash = sha256 (dedup doc-level như cũ, pipeline.py:48-51)
  │  source_url = file:///... (citation trỏ về file gốc)
  ▼
extract_pages_hybrid(bytes, ocr)                 [MỚI — ingestion/knowledge/pdf_ocr.py]
  │  mỗi trang: pdfplumber text ≥ NGƯỠNG (50 ký tự) → dùng luôn
  │             ngược lại → PyMuPDF render PNG 200 DPI → Gemini OCR → markdown
  ▼
resolve_metadata(first_pages_text, filename)     [MỚI — classify {school, year}]
  ▼
pages_to_marked_text → split_into_chunks → embed → upsert_chunk   [GIỮ NGUYÊN]
  (topic=NULL, document_type=<folder>, school/year từ classify)
```

## 5. Thành phần chi tiết

### 5.1. `ingestion/knowledge/pdf_ocr.py` (mới)

- `extract_pages_hybrid(content: bytes, ocr: Callable) -> HybridPagesResult`
  - Trả per-page `(page_no, text, method)` với `method ∈ {"text_layer", "ocr", "failed"}`
    + thống kê `pages_text/pages_ocr/pages_failed`.
  - Ngưỡng text layer: **50 ký tự sau strip** (bản per-page của heuristic
    `_refine_pdf_type` sẵn có). Hằng số module, có thể chỉnh.
  - Render: PyMuPDF, `matrix` tương đương ~200 DPI, xuất PNG bytes.
- OCR callable mặc định gọi gateway:
  - `agent_name="knowledge_ocr"`, `task_type="page_ocr"`, `output_mode="free_text"`,
    `temperature=0.0`, `media=[("image/png", png_bytes)]`.
  - Prompt: "Phiên âm toàn bộ nội dung trang tài liệu sang markdown tiếng Việt.
    Bảng → bảng markdown. Giữ nguyên số liệu, không suy diễn; đoạn không đọc được
    đánh dấu `[không đọc được]`. Không thêm lời dẫn."

### 5.2. Mở rộng gateway đa phương thức (`services/inference/`)

- `InferenceRequest` thêm field: `media: List[Tuple[str, bytes]] = []`
  (mime type, raw bytes). Pydantic v2, default rỗng → **không ảnh hưởng call site cũ**.
- `GeminiProvider._call`: khi `request.media` không rỗng, build
  `contents=[types.Part.from_bytes(...), request.user_prompt]`; ngược lại giữ nguyên
  `contents=request.user_prompt`.
- Gateway/registry/key-pool/telemetry **không đổi** — `knowledge_ocr` chỉ là một
  `agent_name` mới (dùng default model, `allow_fallback=True` qua override registry
  nếu cần).

### 5.3. Metadata resolution (mới, trong `pdf_ocr.py` hoặc module nhỏ riêng)

Thứ tự ưu tiên cho mỗi file **mới**:
1. `overrides.json` (nếu có entry theo tên file) — `{ "<filename>": {"school": "HUST", "year": 2026} }`.
2. LLM classify từ text trang 1–2 (sau hybrid extract): 1 call gateway,
   `output_mode="json"`, schema `{school, year}`. `school` **ràng buộc** vào danh sách
   mã trường đang dùng trong corpus (`HUST`, `NEU`, `VNU-UET` — đồng bộ với
   `knowledge_sources.json` và intent router) hoặc `"unknown"`.
3. Năm: nếu LLM không chắc, regex `\b20\d{2}\b` từ tên file.
4. Bất khả kháng → `school="unknown"` + **WARNING** trong summary (file vẫn ingest;
   cảnh báo để người dùng thêm override rồi chạy lại).

**Áp override cho file ĐÃ ingest (không tốn OCR):** vòng skip theo `content_hash`
chỉ áp dụng khi file **không có** entry trong `overrides.json`. Nếu hash không đổi
nhưng có override → re-ingest **từ `knowledge_documents.raw_text` đã lưu** (bỏ qua
bước extract/OCR), re-chunk + upsert với metadata mới; embedding tái dùng theo
`content_hash` chunk nên gần như miễn phí.

### 5.4. Tích hợp pipeline (`ingestion/knowledge/pipeline.py`)

- `run_for_local_dir(root: Path) -> list[KnowledgeIngestResult]`:
  - Quét `pdf_text/**/*.pdf` + `pdf_scanned/**/*.pdf`.
  - Mỗi file: hash → skip nếu doc đã ingest, hash không đổi **và không có override**
    (có override → re-ingest từ `raw_text` đã lưu, xem 5.3).
  - Hybrid extract → metadata resolve → chunk → embed (tái dùng embedding theo
    content_hash như cũ) → upsert chunks với `school`, `year`,
    `topic=None`, `document_type=<tên folder cấp 1>`, `source_url=file:///...`.
- `KnowledgeIngestResult` thêm: `pages_text: int`, `pages_ocr: int`,
  `pages_ocr_failed: int`, `school: str`.
- CLI: thêm `--local-dir <path>` vào `_main` (mutually exclusive với
  `--school/--all` hiện có).
- Summary cuối in mỗi file một dòng:
  `OK <file> school=HUST year=2026 pages(text/ocr/fail)=3/12/0 chunks=41` + các WARNING.

### 5.5. Sửa retrieval (`services/knowledge/repository.py`)

- `vector_search`: điều kiện topic đổi từ `AND topic = %s` thành
  `AND (topic = %s OR topic IS NULL)`. (`search_by_metadata` giữ nguyên —
  caller truyền topic tường minh.)
- Hành vi: chunk từ web source (có topic) giữ nguyên lọc cứng; chunk PDF local
  (topic NULL) luôn là ứng viên, vector similarity quyết định thứ hạng.

### 5.6. Folder-intent cross-check (quality gate)

- File trong `pdf_text/` nhưng >50% trang phải OCR →
  `WARNING: <file> có vẻ là scan, nên chuyển sang pdf_scanned/` (vẫn xử lý bình thường).
- File trong `pdf_scanned/` nhưng 100% trang có text layer → `INFO` (không tốn OCR).

## 6. Vì sao bỏ phân loại `topic`/`document_type` (ghi lại lập luận)

- `document_type` **không xuất hiện** trong bất kỳ truy vấn retrieval nào
  (`vector_search`/`search_by_metadata` chỉ lọc school+topic) → đoán bằng LLM là
  vô ích; lấy tên folder đủ cho debug.
- `topic` là hard filter trong `vector_search` (`repository.py:198-200`) — cơ chế
  này sinh ra cho web source 1-trang-1-chủ-đề. PDF chính thức đa chủ đề (quy chế
  chứa cả học phí + học bổng): gán 1 topic/file rồi lọc cứng làm nội dung vô hình
  với các câu hỏi khác topic. NULL-as-wildcard (D6) giải quyết đúng tầng SQL với
  1 dòng sửa; per-chunk topic là tối ưu hoá precision để sau (corpus còn nhỏ).

## 7. Xử lý lỗi

| Tình huống | Hành vi |
|---|---|
| 1 trang OCR `InferenceError` | `logger.warning`, đếm `pages_ocr_failed`, **tiếp tục** trang khác (convention degrade gracefully) |
| Toàn bộ trang fail / tổng text rỗng | **Raise** — không `mark_ingested`, để re-run sau còn retry (nếu mark thì content_hash skip vĩnh viễn = tái diễn bug gốc) |
| Classify school fail / không chắc | `school="unknown"` + WARNING; ingest vẫn chạy; sửa bằng `overrides.json` + re-run |
| File PDF hỏng (PyMuPDF/pdfplumber raise) | Log error, skip file đó, tiếp tục file khác (pattern `run_for_school` sẵn có) |
| Gemini quota/key hết giữa chừng | `InferenceError` per-page → như hàng 1; file fail toàn bộ → như hàng 2 |

## 8. Idempotency & chi phí

- Doc-level: `content_hash` skip (sẵn có) ⇒ file không đổi không bao giờ OCR/classify/embed lại.
- Chunk-level: embedding reuse theo `content_hash` toàn corpus (sẵn có).
- Ước lượng one-off: <50 file × ~10–20 trang ≈ 500–1000 call OCR + ~50 call classify.
- File đổi nội dung → OCR lại toàn bộ file đó (chấp nhận ở quy mô này; page-cache là việc sau).

## 9. Testing

Theo pattern fake/inject sẵn có ở `tests/ingestion/knowledge/`:

1. `pdf_ocr`: trang có text layer → không gọi OCR; trang rỗng → gọi OCR (fake);
   ngưỡng 50 ký tự; thống kê pages_text/ocr/failed; 1 trang fail → tiếp tục;
   toàn bộ fail → raise.
2. Provider: `InferenceRequest.media` → contents đa phương thức (mock client,
   không network); không media → hành vi cũ nguyên vẹn.
3. Metadata: override thắng classify; classify trả school ngoài danh sách → "unknown";
   year fallback từ filename; override trên file đã ingest (hash không đổi) →
   re-ingest từ `raw_text` đã lưu, **không** gọi OCR/extract lại.
4. `run_for_local_dir`: quét 2 folder; skip theo content_hash; topic=NULL +
   document_type=folder trên chunk; summary có warning folder-mismatch.
5. `vector_search`: chunk topic NULL được trả về khi lọc topic; chunk topic khác
   vẫn bị loại (regression cho web source).
6. Probe thủ công (`scripts/ocr_probe.py`, theo convention scripts/ một-lần):
   chạy 1–2 file thật, in markdown để eyeball chất lượng OCR.

## 10. Dependency & footprint

- Mới: `pymupdf` (pip-only). Không thêm binary hệ thống.
- Footprint code: 1 module mới (`pdf_ocr.py`), 1 field + 1 nhánh provider,
  1 method + 1 CLI arg trong pipeline, 1 dòng SQL trong `vector_search`,
  `.gitignore` thêm `data/knowledge/`.
