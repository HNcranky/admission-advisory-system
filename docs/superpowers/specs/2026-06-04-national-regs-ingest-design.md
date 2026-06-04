# Thiết kế: Ingest văn bản tuyển sinh nhà nước (phạm vi toàn quốc)

- **Ngày:** 2026-06-04
- **Trạng thái:** Draft (chờ review)
- **Phạm vi:** Knowledge/RAG ingestion (`ingestion/knowledge/`), truy hồi knowledge (`services/chat/knowledge_fanout.py`), hằng số scope (`ingestion/knowledge/local_metadata.py`)
- **Động lực gốc:** Quy chế tuyển sinh của Bộ GD&ĐT **ràng buộc cách xét tuyển của mọi trường** (điểm ưu tiên khu vực/đối tượng, ngưỡng đảm bảo chất lượng, quy định xét tuyển sớm, quy đổi điểm…). Hiện corpus chỉ có tài liệu **theo từng trường**; thiếu lớp văn bản nhà nước này khiến tư vấn theo trường bỏ sót đúng các quy định đang chi phối câu trả lời.

---

## 1. Bối cảnh & vấn đề

Pipeline knowledge hiện gắn mỗi tài liệu với một `school` (HUST/NEU/VNU-UET) và truy hồi **lọc cứng theo trường** (`services/knowledge/repository.py::vector_search` → `WHERE school = %s` khi có school; `services/chat/knowledge_fanout.py` fan-out theo trường của intent). Mô hình này đúng cho tài liệu của trường, nhưng **không có chỗ cho văn bản áp dụng-toàn-quốc**: một Thông tư của Bộ GD&ĐT không thuộc về một trường, nhưng phải bổ trợ cho câu hỏi về *bất kỳ* trường.

Đã trinh sát hai nguồn để lấy các văn bản này:

- **`thuvienphapluat.vn`** — bên thứ ba thương mại, nội dung sau đăng nhập/paywall, điều khoản cấm thu thập tự động. **Loại.**
- **`vbpl.vn`** (CSDL quốc gia) — robots cho phép (`Allow: /`, chỉ chặn `/api/`), nhưng **trang tìm kiếm và trang văn bản đều render bằng JS**; HTML thô không chứa toàn văn hay link tải file. Crawler tĩnh (BeautifulSoup) thấy rỗng → cần Playwright (ngoài phạm vi). **Loại.**
- **`vanban.chinhphu.vn`** (cổng văn bản Chính phủ) — robots `Allow: /`; **trang văn bản là HTML tĩnh chứa thẳng link PDF ký số** trên `datafiles.chinhphu.vn`. Ví dụ đã xác minh: Thông tư 08/2022/TT-BGDĐT → `https://datafiles.chinhphu.vn/cpp/files/vbpq/2022/08/08-bgddt.signed.pdf`. **Đây là nguồn dùng được** cho pipeline PDF hiện tại.

Hạ tầng tái dùng được ngay: `KnowledgePipeline.run_for_url(url, *, school, document_type, ocr, classify)` (fetch → `extract_pages_hybrid` text+OCR → `_chunk_embed_upsert` → `mark_ingested`, citation = URL gốc, skip theo `content_hash`); fan-out per-(school, topic) ở `knowledge_fanout.py`; `http_fetch` (SSL-off mặc định + retry).

## 2. Mục tiêu / Ngoài phạm vi

**Mục tiêu**
- G1. Nạp một **tập nhỏ curated** PDF văn bản tuyển sinh nhà nước (nguồn `datafiles.chinhphu.vn`) vào corpus dưới scope sentinel `school="MOET"`, dùng hybrid extractor (text + OCR), citation = URL chinhphu.
- G2. Văn bản nhà nước **nổi lên trong mọi câu trả lời knowledge** — cả câu hỏi theo trường cụ thể lẫn câu hỏi chính sách chung — mà **không pha loãng** kết quả của từng trường.
- G3. **Không crawl, không migration DB.** Tái dùng `run_for_url` + fan-out + cột `school` sẵn có.
- G4. Cô lập lỗi & idempotent: 1 URL lỗi không chết cả phiên; chạy lại không OCR/embed lại nhờ `content_hash`.
- G5. Test offline qua dependency injection (`fetch`/`ocr`/`classify`).

**Ngoài phạm vi (YAGNI)**
- Crawl/tự động khám phá theo từ khóa trên chinhphu hay vbpl — tập văn bản nhỏ & ổn định nên **curated bằng tay**.
- Ingest trang HTML toàn văn / Playwright cho trang render-JS (vbpl.vn) — loại.
- Cột `scope` riêng hoặc bảng "policy" riêng — sentinel `school="MOET"` mượn cột `school` là đủ.
- Tự động phát hiện Thông tư mới ban hành — người dùng thêm URL vào config khi có.

## 3. Quyết định kiến trúc (đã chốt qua brainstorm)

| # | Quyết định | Lý do |
|---|---|---|
| D1 | **Văn bản nhà nước nổi lên ở MỌI truy vấn** (không chỉ câu hỏi chung) | Quy chế của Bộ chi phối cách xét tuyển của mọi trường; chỉ hiện ở câu hỏi chung sẽ bỏ sót đúng quy định ràng buộc câu trả lời theo trường |
| D2 | **Sentinel `school="MOET"`** (mượn cột `school`), không thêm cột/bảng | Ít xâm lấn nhất, không migration; `KNOWN_SCHOOLS` chỉ là registry nhãn, không rò ra UI/intent router (đã xác minh) |
| D3 | **Lượt fan-out quốc gia là phần mặc định của fan-out (block + top-k riêng), bỏ qua khi truy vấn không gắn trường** | `vector_search(school="MOET")` tách ngân sách riêng → văn bản nhà nước không lấn át chunk của trường trong một top-k chung; nhánh `school=None` đã bao gồm MOET nên không cần lượt riêng |
| D4 | **Curated URL list + ingest theo URL**, nguồn `datafiles.chinhphu.vn` | Tập nhỏ-ổn-định; PDF ký số chính thống tải tĩnh được; `run_for_url` đã nhận `bytes` + OCR |
| D5 | **Config curated tách khỏi manifest** (`seeds/national_sources.json`, version-controlled) | Manifest là vùng gitignored cho ứng viên crawl; danh sách văn bản nhà nước nên nằm trong git, tách bạch với PDF crawl theo trường |

## 4. Kiến trúc & luồng dữ liệu

```
seeds/national_sources.json  (curated: URL PDF ký số chính thống + title)
        │
        ▼
[1] ingest_national CLI ── mỗi URL: run_for_url(school="MOET",
        │                   document_type="national_regulation")
        ▼
   fetch PDF (datafiles.chinhphu.vn) → extract_pages_hybrid (text + OCR)
        │   → chunk/embed/upsert (school="MOET") → mark_ingested (skip nếu content_hash trùng)
        ▼
   knowledge_chunks: school="MOET", document_type="national_regulation", source_url = URL chinhphu

[ Truy hồi lúc hỏi ]
   intent → run_knowledge_fanout:
        cho mỗi trường cụ thể intent giải ra (HUST/…) → lượt theo trường
        + một lượt school="MOET"                      → block "Quy định chung (Bộ GD&ĐT)"
          (BỎ QUA nếu tập trường giải ra là [None] — nhánh school=None đã quét cả MOET)
   → [<block trường>…, <block quốc gia>] → synthesis / inline answer
```

## 5. Thành phần

### 5.1 `ingestion/knowledge/seeds/national_sources.json`
Danh sách curated, version-controlled. Mỗi mục tối thiểu `{url, title}`; `school` ngầm định là `"MOET"`.
```json
[
  {"url": "https://datafiles.chinhphu.vn/cpp/files/vbpq/2022/08/08-bgddt.signed.pdf",
   "title": "Thông tư 08/2022/TT-BGDĐT — Quy chế tuyển sinh đại học"}
]
```
Cách lấy URL mỗi văn bản: mở trang văn bản trên `vanban.chinhphu.vn` → copy link file đính kèm trỏ về `datafiles.chinhphu.vn/.../*.signed.pdf`. Người dùng thêm dòng mới khi có Thông tư sửa đổi/ban hành mới (vd 06/2025/TT-BGDĐT).

### 5.2 Hằng số scope (`ingestion/knowledge/local_metadata.py`)
- Thêm `NATIONAL_SCHOOL = "MOET"`.
- Đưa `"MOET"` vào `KNOWN_SCHOOLS` để làm registry nhãn hợp lệ (đã xác minh `KNOWN_SCHOOLS` chỉ được dùng bởi `local_metadata` + `crawler/config.py` validator + test; **không** rò vào intent router hay picker chọn trường của sinh viên — router trích tên trường bằng prompt LLM tự do, `preferred_schools` là list tự do).
- Hằng `NATIONAL_DOCUMENT_TYPE = "national_regulation"` (phân biệt với `crawled_pdf`/`pdf_text`/`pdf_scanned`).

### 5.3 CLI `python -m ingestion.knowledge.ingest_national`
Gương `ingestion/knowledge/ingest_manifest.py`:
- Đọc `national_sources.json`.
- Mỗi mục: `pipeline.run_for_url(url, school=NATIONAL_SCHOOL, document_type=NATIONAL_DOCUMENT_TYPE)`.
- `try/except` cô lập **từng URL** (`log + continue`).
- In summary `OK / SKIP / FAIL` cho mỗi URL (kể cả file lỗi — không ẩn lỗi khỏi summary).
- Idempotent: `run_for_url` đã skip khi `content_hash` trùng.

`run_for_url` **không cần sửa** — nó đã nhận `school` tường minh (không classify school), chỉ điền `year`, citation = URL.

### 5.4 Lượt fan-out quốc gia (`services/chat/knowledge_fanout.py`)
- `run_knowledge_fanout` **luôn bổ sung** một lượt `school=NATIONAL_SCHOOL` ngoài (các) trường mà `_resolve_schools` trả về, cho mỗi topic đã giải.
- Lượt này tạo một `KnowledgeBlock` nhãn **"Quy định chung (Bộ GD&ĐT)"** (không gắn tên một trường).
- **Dedup:** khi `_resolve_schools` trả `[None]` (câu hỏi chung — nhánh `school=None` của `vector_search` vốn quét cả chunk MOET), loại trùng theo `source_url` để không lặp nội dung/citation giữa block chung và block quốc gia. Cụ thể: nếu đã có lượt `school=None`, **không** chạy thêm lượt `school="MOET"` (vì đã bao gồm); chỉ thêm lượt MOET khi tập trường giải ra là các trường cụ thể.
- Mỗi lượt vẫn nuốt lỗi riêng → no-data block, các lượt khác sống (hành vi fan-out sẵn có).

## 6. Xử lý lỗi & độ bền (kế thừa pattern hiện có)

- **Cô lập từng URL** ở `ingest_national`: `try/except` quanh mỗi `run_for_url`.
- `HybridExtractionError` (PDF rỗng / OCR fail toàn bộ) → **không** `mark_ingested` (tránh hash-skip che lỗi); báo FAIL trong summary.
- OCR fail từng trang → degrade (hành vi `extract_pages_hybrid`).
- `classify` (chỉ điền `year`) fail → fallback theo tên file; `school` cố định `"MOET"` nên **không** có vụ `school=unknown`.
- Lượt fan-out MOET lỗi → no-data block; siblings sống.
- **Mạng:** `http_fetch` SSL-off mặc định lo cert `.gov.vn`, log mỗi fetch; robots `datafiles/vanban.chinhphu.vn` = `Allow: /`.

## 7. CLI

```bash
# Nạp/chạy lại văn bản nhà nước (idempotent)
python -m ingestion.knowledge.ingest_national
#   → in OK/SKIP/FAIL mỗi URL
```
Không có pha "duyệt" như crawl-manifest: danh sách đã curated trong `national_sources.json`.

## 8. Mô hình dữ liệu

Không thêm bảng/cột. Chunk/Document dùng schema sẵn có với:
- `school = "MOET"` (sentinel scope toàn quốc)
- `document_type = "national_regulation"`
- `source_url` = URL `datafiles.chinhphu.vn` (citation trỏ nguồn chính thống)
- `year` = năm Thông tư (classifier điền, fallback theo tên file)

## 9. Chiến lược test (offline, DI)

- **`ingest_national`** với `fetch`/`ocr`/`classify` giả + PDF fixture: assert gọi `run_for_url(school="MOET", document_type="national_regulation")` cho từng URL; một URL lỗi không chặn URL còn lại; summary đếm OK/SKIP/FAIL đúng.
- **Loader `national_sources.json`** round-trip (đọc danh sách, bỏ qua dòng hỏng).
- **Fan-out:** với intent có trường cụ thể → assert có **đúng một** lượt `school="MOET"` kèm các lượt trường, và sinh block "Quy định chung"; với intent không trường (`school=None`) → assert **không** thêm lượt MOET trùng (dedup).
- **Integration (cần Docker DB):** ingest 1 reg fixture qua `ingest_national` → assert có row `school="MOET"` trong `knowledge_chunks`; `vector_search(school="MOET")` trả về; và một truy vấn theo trường cụ thể vẫn kèm block quốc gia.

## 10. Rủi ro & lưu ý

- **URL `datafiles.chinhphu.vn` đổi đường dẫn:** nếu Chính phủ đổi cấu trúc file, ingest 1 URL sẽ FAIL (cô lập, in rõ trong summary). Sửa URL trong `national_sources.json`.
- **Trùng nội dung giữa block chung và block quốc gia:** đã xử lý bằng quy tắc dedup ở §5.4 (không chạy lượt MOET khi đã có lượt `school=None`).
- **Sentinel `school="MOET"` lọt vào thống kê theo trường:** mọi báo cáo/đếm theo `school` sẽ thấy "MOET" như một nhãn; chấp nhận được vì nó đúng là một scope hợp lệ trong `KNOWN_SCHOOLS`. Không hiển thị "MOET" như một trường để sinh viên chọn (picker không lấy từ `KNOWN_SCHOOLS`).
- **`pymupdf` phải được cài** (điều kiện tiên quyết của OCR/hybrid extractor, dùng chung với luồng ingest hiện có).
