# Scanned-PDF Knowledge OCR — Plan Index

> Spec gốc: `docs/superpowers/specs/2026-06-04-scanned-pdf-knowledge-ocr-design.md`

Đưa PDF scan (không có text layer) vào luồng knowledge embedding: OCR từng trang
qua Gemini vision, auto-discovery 2 folder local, metadata classify `{school, year}`,
`topic=NULL` làm wildcard trong retrieval.

## Các plan & thứ tự thực hiện

| # | Plan | Phạm vi | Phụ thuộc |
|---|------|---------|-----------|
| 01 | [Gateway multimodal media](01-gateway-multimodal-media.md) | `services/inference/` — field `media` trên `InferenceRequest`, nhánh đa phương thức trong `GeminiProvider._call`, đăng ký agent `knowledge_ocr` + `knowledge_classify` | — |
| 02 | [Hybrid PDF extractor + OCR](02-pdf-ocr-hybrid-extractor.md) | `ingestion/knowledge/pdf_ocr.py` mới — text layer ≥ 50 ký tự dùng luôn, trang ảnh render PNG ~200 DPI (PyMuPDF) → Gemini OCR; dependency `pymupdf`; probe script | 01 |
| 03 | [Local metadata resolution](03-local-metadata-resolution.md) | `ingestion/knowledge/local_metadata.py` mới — `overrides.json` thắng LLM classify, school whitelist, year fallback từ tên file | 01 |
| 04 | [vector_search NULL topic](04-vector-search-null-topic.md) | `services/knowledge/repository.py` — `AND (topic = %s OR topic IS NULL)`; chunk PDF local (topic NULL) luôn là ứng viên retrieval | — (độc lập hoàn toàn) |
| 05 | [Local-dir pipeline + CLI](05-local-dir-pipeline-and-cli.md) | `ingestion/knowledge/pipeline.py` — `run_for_local_dir`, skip theo content_hash, override re-ingest từ `raw_text`, folder-intent warning, CLI `--local-dir`, summary, `.gitignore` | 02, 03 |

```
01 ──► 02 ──┐
01 ──► 03 ──┼──► 05
04 (độc lập)┘
```

Thứ tự đề xuất: **01 → 02 → 03 → 04 → 05** (04 có thể chen vào bất kỳ lúc nào).

## Quyết định kiến trúc đã chốt (từ spec, không bàn lại khi triển khai)

- **D1** OCR engine = Gemini vision qua gateway sẵn có (`build_default_gateway()`).
- **D2** Hybrid theo trang: text layer ≥ 50 ký tự sau strip → dùng luôn; ngược lại render + OCR.
- **D3** Folder là *ý định*: cả 2 folder chạy cùng extractor hybrid; lệch thực tế → WARNING.
- **D4** Auto-discovery, không đăng ký từng file vào JSON nào.
- **D5** LLM classify chỉ `{school, year}`; school ràng buộc vào `HUST`, `NEU`, `VNU-UET` hoặc `"unknown"`.
- **D6** `topic = NULL` cho PDF local + `vector_search` coi NULL là wildcard.
- **D7** `document_type` = tên folder (`pdf_text` / `pdf_scanned`).
- **D8** Render bằng PyMuPDF (`pymupdf`, pip-only), ~200 DPI PNG.

## Lệnh kiểm tra chung

```powershell
# Unit (không cần DB)
.\.venv\Scripts\python.exe -m pytest -q

# Integration (plan 04) cần Docker DB
docker compose up -d --wait db
.\.venv\Scripts\python.exe -m db.setup_db
.\.venv\Scripts\python.exe -m pytest tests\services\knowledge\test_repository_integration.py -q

# Acceptance cuối (plan 05) — cần GEMINI_API_KEY(S) trong shell
.\.venv\Scripts\python.exe -m ingestion.knowledge.pipeline --local-dir data\knowledge
```

> **Lưu ý repo:** không bao giờ `git push`; commit message KHÔNG kèm attribution AI.
