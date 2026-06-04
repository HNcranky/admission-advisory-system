# Thiết kế: Tự động thu thập PDF tuyển sinh (discover → duyệt → ingest)

- **Ngày:** 2026-06-04
- **Trạng thái:** Draft (chờ review)
- **Phạm vi:** Knowledge/RAG ingestion (`ingestion/knowledge/`), fetcher (`ingestion/fetchers/`), knowledge pipeline (`ingestion/knowledge/pipeline.py`)
- **Động lực gốc:** Mỗi trường có **rất nhiều** tài liệu PDF rải khắp web. Tìm và dán từng URL bằng tay (`knowledge_sources.json`) hoặc tải tay từng file (`--local-dir`) vừa **mất thời gian** vừa **dễ sót**. Cần một bước *discovery* biến trang web của trường thành một danh sách tài liệu để duyệt nhanh rồi ingest.

---

## 1. Bối cảnh & vấn đề

Hai đường nạp dữ liệu knowledge hiện tại đều **thủ công**:

1. **URL-based** (`KnowledgePipeline.run_for_source` + `knowledge_sources.json`) — phải biết và dán chính xác từng URL. Ngoài ra đường này dùng `_extract_text` → `extract_pages` (pdfplumber) **không OCR**, nên PDF scan tải theo URL sẽ ra rỗng.
2. **Local file** (`run_for_local_dir` + `--local-dir`, branch `feat/pdf-reader`) — phải tự tải PDF về rồi bỏ vào `pdf_text/` `pdf_scanned/`. Đường này có hybrid extract (text-layer + OCR) + classify school/year, nhưng người dùng vẫn phải đi tải tay.

Cái còn thiếu là **discovery**: không có gì tự duyệt web trường để liệt kê PDF. Hệ quả: nạp dữ liệu chậm và **sót tài liệu**.

Hạ tầng tái dùng được ngay: `http_fetch` (retry + SSL-off mặc định cho `.gov.vn`), `parse_html`, `extract_pages_hybrid` (nhận `bytes`), `build_gateway_ocr`/`build_gateway_classifier`, `_chunk_embed_upsert`, repository + skip theo `content_hash`.

## 2. Mục tiêu / Ngoài phạm vi

**Mục tiêu**
- G1. Tự động duyệt web mỗi trường (từ seed URL) và **liệt kê mọi PDF** tìm được vào một manifest, kèm thông tin giúp duyệt (anchor text, trang nguồn, size, relevance tag).
- G2. **Chống sót:** crawl lại thì *merge* — giữ quyết định cũ, PDF mới xuất hiện dạng `pending`.
- G3. Khâu duyệt do người: chỉ entry được đánh `keep` mới ingest. Tránh nuốt rác (biểu mẫu, văn bản cũ).
- G4. Ingest entry `keep` **trực tiếp theo URL** dùng **hybrid extractor** (text-layer + OCR) + classify school/year; citation trỏ về URL gốc của trường.
- G5. Cô lập lỗi: 1 trang/PDF/URL lỗi không làm chết cả phiên crawl hay phiên ingest.
- G6. Idempotent: crawl lại không làm mất quyết định; ingest lại không OCR/embed lại nhờ `content_hash` skip.
- G7. Mọi LLM call đi qua `build_default_gateway()`, degrade gracefully khi `InferenceError` (đúng convention repo).
- G8. Test được offline: crawler & ingest-by-URL nhận `fetch`/`ocr`/`classify` qua dependency injection.

**Ngoài phạm vi (YAGNI)**
- Crawl trang render bằng JS (Playwright) — phần lớn trang tuyển sinh `.edu.vn` là tĩnh; thêm sau nếu cần.
- Tích hợp search engine (đã loại ở brainstorm — xem mục 3).
- Tự động ingest trang HTML (học phí/học bổng) — giữ ở `knowledge_sources.json` thủ công; feature này chỉ lo PDF.
- Lịch chạy tự động (cron) — chạy tay bằng CLI; có thể bọc `/loop`/cron sau.
- Cache OCR theo trang — thừa hưởng quyết định YAGNI của spec OCR (`2026-06-04-scanned-pdf-knowledge-ocr-design.md`).

## 3. Quyết định kiến trúc (đã chốt qua brainstorm)

| # | Quyết định | Lý do |
|---|---|---|
| D1 | **Discover → duyệt → ingest** (có lớp manifest do người duyệt), không fully-auto | Dữ liệu chính thức nuôi advisory; cần kiểm soát chất lượng, tránh nuốt rác, mà vẫn nhanh hơn dò tay |
| D2 | **Focused crawler theo trường** (seeds + BFS cùng domain + sitemap booster), không dùng search API | Không phụ thuộc API/chi phí ngoài; tái dùng `http_fetch`; đủ phủ cho site `.edu.vn` tĩnh |
| D3 | **Ingest trực tiếp theo URL bằng hybrid extractor**, không tải về folder rồi `--local-dir` | Citation trỏ URL trường; không thao tác tay; `extract_pages_hybrid` đã nhận `bytes` nên tái dùng được |
| D4 | **Liệt kê MỌI PDF**, dùng `relevance` tag chỉ để gợi ý — không lọc bỏ ở khâu crawl | Mục tiêu chống sót: quyết định bỏ là việc của người duyệt, không phải heuristic |
| D5 | Manifest là **JSON** đặt tại `data/knowledge/manifest.json` (cùng gốc corpus, đã gitignore) | Người dùng sửa hàng loạt bằng editor; nằm trong vùng không commit |
| D6 | Khâu crawl và khâu ingest là **2 lệnh CLI tách biệt**, ở giữa là người duyệt | Phản ánh đúng 3 pha; ingest chỉ đụng entry `keep` |

## 4. Kiến trúc & luồng dữ liệu

```
crawler_targets.json (config mỗi trường)
        │
        ▼
[1] PDF Crawler ── BFS cùng domain từ seeds + đọc sitemap.xml
        │            gom mọi link .pdf (+ anchor text, trang nguồn, size/last-modified qua HEAD)
        ▼
[2] manifest.json ── 1 dòng/PDF: status="pending", relevance, already_ingested
        │            crawl lại → MERGE (giữ quyết định cũ, PDF mới = pending)
        ▼
[ NGƯỜI duyệt ]  ── sửa status: keep / skip (sửa school nếu cần)
        │
        ▼
[3] Ingest-by-URL ── mỗi entry keep: fetch PDF → extract_pages_hybrid (text + OCR)
                     → classify school/year → _chunk_embed_upsert → mark_ingested
                     → set status="done". Citation = URL gốc trường.
```

## 5. Thành phần

Module mới **`ingestion/knowledge/crawler/`** (đặt cạnh `knowledge/` cho đồng bộ cấu trúc):

### 5.1 `crawl_config.py` + seed `crawler_targets.json`
Config mỗi trường (Pydantic v2 `model_config = ConfigDict(...)`):
```json
{"school":"HUST",
 "seeds":["https://ts.hust.edu.vn/","https://www.hust.edu.vn/tuyen-sinh"],
 "allow_domains":["hust.edu.vn"],
 "allow_path_prefixes":["/tuyen-sinh","/uploads"],
 "max_depth":2, "max_pages":300}
```
- `school` phải khớp `KNOWN_SCHOOLS` (HUST/NEU/VNU-UET) để classify/vector_search lọc đúng.
- `allow_path_prefixes` rỗng = cho phép cả domain.

### 5.2 `pdf_crawler.py`
- BFS queue `(url, depth)` từ `seeds`; `visited` set; tôn trọng `max_depth` + `max_pages`.
- Mỗi trang HTML: trích `<a href>` (BeautifulSoup — đã là dep qua parsers), resolve relative → absolute, **chuẩn hóa** (bỏ fragment `#`, trailing slash, query tracking), lọc theo `allow_domains` + `allow_path_prefixes`.
- Phân loại link: đuôi `.pdf` (hoặc content-type `application/pdf` qua HEAD) → ứng viên PDF; HTML cùng domain trong depth → enqueue.
- Đọc `sitemap.xml` (kể cả sitemap lồng nhau) cho mỗi domain → thêm URL `.pdf`.
- Mỗi PDF ứng viên: 1 HEAD lấy `content-type`/`content-length`/`last-modified` (chưa tải nội dung). HEAD trả 405 → bỏ qua các field này, vẫn ghi nhận URL.
- **Inject `fetch=`** (mặc định `http_fetch`) để test offline.
- Trả `list[CandidatePdf]`.

### 5.3 `manifest.py`
- Đọc/ghi `data/knowledge/manifest.json`.
- **Merge** khi crawl lại: URL đã có → giữ nguyên `status`; URL mới → thêm `status="pending"`.
- Đánh `already_ingested` bằng `doc_repo.get_document_by_url(url)`.
- Tính `relevance` (`high`/`low`) theo từ khóa trong anchor text/URL: *tuyển sinh, đề án, chỉ tiêu, thông báo, phương thức, học phí*... — **chỉ gợi ý, không lọc**.

### 5.4 Ingest-by-URL (nâng cấp pipeline)
Thêm `KnowledgePipeline.run_for_url(url, *, school, document_type="crawled_pdf")` (hoặc `run_for_manifest_entry`) gương theo `run_for_local_file`:
```
fr = self.fetch(url); content = fr.raw_content
existing = doc_repo.get_document_by_url(url)
if existing and existing.content_hash == fr.content_hash: skip
hybrid = extract_pages_hybrid(content, ocr)
text = pages_to_marked_text(hybrid.to_page_tuples())
year = classify_year(first_pages, filename_from_url)   # chỉ điền year
_chunk_embed_upsert(school=school, year=year, document_type=document_type, ...)
mark_ingested(content_hash)
```
- **`school` lấy từ manifest entry (= config trường đã crawl), là nguồn chuẩn** — không cần classify đoán school (PDF tìm thấy dưới `hust.edu.vn` luôn là HUST). Nhờ vậy luồng crawl **không gặp vấn đề `school=unknown`** như local flow.
- `classify` chỉ còn nhiệm vụ điền `year` (fallback `year_from_filename`); degrade gracefully khi `InferenceError`.
- `document_type` mặc định hằng số `"crawled_pdf"` (phân biệt với `pdf_text`/`pdf_scanned` của local flow).
- `run_for_source` cũ **giữ nguyên** (không phá luồng URL hiện tại); đây là đường mới có OCR.

## 6. Xử lý lỗi & độ bền

- **Cô lập lỗi từng URL** ở cả crawl lẫn ingest: `try/except` quanh mỗi URL, `log + continue` (đúng pattern `run_for_local_dir`).
- **Chống crawl loạn:** `max_depth` + `max_pages` mỗi trường; `visited`; chuẩn hóa URL chống lặp.
- **Lịch sự:** tái dùng UA ngẫu nhiên + retry/backoff của `http_fetch`; delay nhỏ giữa request; đọc `robots.txt` (mặc định tôn trọng; cờ `--ignore-robots`). SSL-off theo mặc định repo, log mỗi fetch.
- **HEAD 405** → fallback bỏ qua metadata size, không bỏ sót URL.
- **Khâu ingest** kế thừa độ bền sẵn có: `HybridExtractionError` khi PDF rỗng/OCR-fail toàn bộ → **không** mark ingested (tránh hash-skip che lỗi); OCR fail từng trang → degrade; classify (year) fail → fallback `year_from_filename`, không chặn ingest (`school` đã có sẵn từ config).
- **Ghi DB an toàn:** chỉ `status=keep` mới ingest; xong set `done`; chạy lại idempotent nhờ `content_hash`.
- **Summary cuối phiên:** crawl in `pages_crawled / pdfs_found / new / errors`; ingest in `OK/SKIP/FAIL` mỗi entry (kể cả file lỗi — vá điểm "ẩn lỗi khỏi summary" đã thấy ở local flow).

## 7. CLI

```bash
# Pha 1 — discovery (ghi/merge manifest)
python -m ingestion.knowledge.crawl --school HUST       # hoặc --all
#   → data/knowledge/manifest.json  (in: N pages, M pdfs, K new, E errors)

#   ... NGƯỜI duyệt: mở manifest.json, đặt status keep/skip ...

# Pha 3 — ingest entry status=keep
python -m ingestion.knowledge.ingest_manifest           # set "done" sau khi xong
```

## 8. Mô hình dữ liệu manifest

`data/knowledge/manifest.json`, mỗi entry:
```json
{"school":"HUST",
 "url":"https://www.hust.edu.vn/.../de-an-2026.pdf",
 "anchor_text":"Đề án tuyển sinh 2026",
 "found_on":"https://www.hust.edu.vn/tuyen-sinh",
 "content_type":"application/pdf",
 "size_bytes":1234567,
 "last_modified":"2026-03-01",
 "discovered_at":"2026-06-04",
 "relevance":"high",
 "status":"pending",
 "already_ingested":false}
```
`status ∈ {pending, keep, skip, done}`. Người duyệt đổi `pending → keep/skip`; ingest đổi `keep → done`.

## 9. Chiến lược test (bám pattern branch: inject `fetch`/`ocr`/`classify`)

- **Unit offline:**
  - Trích link + chuẩn hóa/lọc URL (allow_domains, allow_path_prefixes, bỏ fragment/dup) — fixture HTML.
  - Parse `sitemap.xml` (kể cả lồng nhau) → list `.pdf`.
  - Merge manifest: giữ status cũ, URL mới = pending, `already_ingested` đúng.
  - Relevance tag theo từ khóa.
- **Crawler BFS với `fetch` giả** trên một "site nhỏ" cố định: đi đúng depth, dừng đúng `max_pages`, gom đúng tập PDF, không ra ngoài domain. Tất định, offline.
- **Ingest-by-URL với `fetch` giả** trả PDF fixture + `ocr`/`classify` giả → chạy hybrid extractor và upsert đúng (gương `tests/ingestion/knowledge/test_pipeline_local.py`).
- **Manifest round-trip** đọc/ghi JSON.
- **Integration (cần Docker DB):** ingest vài PDF fixture qua manifest, assert row trong `knowledge_documents`/`knowledge_chunks` (gương `test_repository_integration.py`).

## 10. Rủi ro & lưu ý

- **Override school không validate** (đã thấy ở local flow): nếu config/manifest đặt sai `school` ngoài `KNOWN_SCHOOLS`, chunk lưu được nhưng `vector_search` lọc cứng nên không tìm thấy. Crawler nên validate `school` của config khớp `KNOWN_SCHOOLS` lúc nạp.
- **Seed URL thay đổi:** trường đổi cấu trúc site → crawl ra 0 PDF. Summary in rõ `pdfs_found=0` để phát hiện sớm; config nằm trong 1 file dễ sửa.
- **`pymupdf` phải được cài** (đã khai báo `requirements.txt`, nhưng OCR sẽ vỡ nếu venv chưa sync) — điều kiện tiên quyết của khâu ingest.
