# Test DB isolation — `admission_test`

**Ngày:** 2026-06-06 · **Trạng thái:** Approved

## Vấn đề

Integration/e2e test dùng chung database `admission` với dev. `clean_db`
(`tests/integration/conftest.py`) TRUNCATE `canonical_admission_records`, và
`test_db_writer_e2e` chỉ re-ingest vnu_uet (20 row) — nên sau mỗi lần chạy
pytest, dữ liệu hust (136 row canonical) biến mất, chỉ còn uet. Ba test khác
TRUNCATE `knowledge_chunks`/`knowledge_documents` — cùng class bug, đã từng để
lại chunk test mồ côi và sẽ xoá corpus knowledge dev. Sự cố tái diễn thực tế
ngày 2026-06-06 (pytest chạy song song với phiên ingest → hust mất giữa chừng).

## Quyết định

Mọi test chạm DB chạy trên database riêng **`admission_test`** (cùng Postgres
server), tự tạo + migrate mỗi session pytest. Dữ liệu dev trong `admission`
không bao giờ bị test động vào.

## Cơ chế

Toàn bộ code (ingestion `db_connection`, `services/chat/db`,
`services/knowledge/db`, `db_writer`, test helpers) đọc tên database từ **một
dict duy nhất** `ingestion.config.settings.DB_CONFIG` *tại thời điểm connect*.
Mutate dict này trong pytest ⇒ mọi connection trong process tự chuyển hướng,
không sửa production code.

### Thay đổi

| File | Nội dung |
|---|---|
| `tests/conftest.py` | Fixture session-scope **autouse** `_isolate_test_db`: probe server (`connect_timeout=2`); nếu server sống → mutate `DB_CONFIG["database"] = "admission_test"`, gọi `create_database()` + `run_migrations()` + `seed_source_registry()` của `db.setup_db` (idempotent, nén stdout, in lại nếu có dòng ⚠️); nếu server tắt → vẫn mutate rồi bỏ qua setup (DB test skip như cũ). Teardown khôi phục tên gốc. |
| `tests/integration/conftest.py` | `db_available` phụ thuộc tường minh `_isolate_test_db` (chốt thứ tự); `clean_db` thêm guard `assert` tên DB kết thúc `_test` trước khi TRUNCATE (defense in depth). |
| 3 file knowledge tests (`test_knowledge_ingestion_e2e.py`, `test_repository_integration.py`, `test_document_repository_integration.py`) | Fixture truncate thêm cùng guard assert trước TRUNCATE. |
| `tests/integration/test_conftest_fixtures.py` | Test regression: khi `db_available` chạy, `DB_CONFIG["database"] == "admission_test"`. |
| `CLAUDE.md` | 1 dòng: pytest chạy trên `admission_test` (tự tạo/migrate), không đụng dữ liệu dev trong `admission`. |

## Hành vi mới

- `pytest` không còn wipe dữ liệu dev; cũng không còn side-effect "tặng" 20 row
  uet vào DB dev.
- Server tắt → DB test skip kèm remediation (không đổi).
- Lỗi migrate trên DB test → fail đầu session, in output lỗi gốc.
- Test ghi mạng thật (`test_db_writer_e2e`) ghi vào `admission_test`.

## Phương án đã loại

1. Inject `connection_factory` từng test — `db_writer`/pipeline không nhận
   factory, phải sửa nhiều production code.
2. Backup/restore quanh test trên DB dev — chậm, vẫn race với phiên dev đang
   chạy (đúng kịch bản sự cố 06/06).
