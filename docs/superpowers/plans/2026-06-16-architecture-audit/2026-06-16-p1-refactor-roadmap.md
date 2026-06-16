# P1 Refactor Roadmap — Cải thiện rủi ro thấp (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (khuyến nghị) hoặc superpowers:executing-plans để thực thi từng task. Các bước dùng checkbox (`- [ ]`) để theo dõi.

**Goal:** Thực thi nhóm **P1** của audit `docs/superpowers/specs/2026-06-16-architecture-audit.md` — thêm timeout LLM, siết input public, gom trùng lặp (DB helper, formatting, fold tiếng Việt), thêm index, và **viết test characterization** mở khóa refactor an toàn — bằng các PR nhỏ, mỗi PR giữ app chạy được, **ưu tiên đơn giản hóa hơn trừu tượng hóa**.

**Architecture:** P1 chia 2 loại thay đổi: (a) *bổ sung/siết* rủi ro rất thấp (index, max_length, timeout ở tầng client factory) — không đụng call-site logic; (b) *gom trùng lặp bảo toàn hành vi* (DB `_cursor`/`vector_literal`, `formatting`, `vietnamese_fold`) — chỉ dời code, không viết lại query/regex. Phần *sửa lệch `đ`* trong fold tiếng Việt là thay đổi hành vi có chủ đích (sửa bug matching) ⇒ **bắt buộc có test characterization trước**.

**Tech Stack:** Python 3.12, `google-genai==1.75.0`, psycopg2, pgvector, FastAPI + Pydantic v2, pytest. Lệnh test chuẩn (Linux): `python -m pytest -q`.

**Quy ước test:** PR bổ sung/siết → TDD cổ điển (viết test đỏ → code → xanh). PR gom-trùng-lặp bảo-toàn-hành-vi → "test đỏ" thay bằng **suite hiện có (đặc biệt test repository/parser) phải xanh trước & sau** + smoke import; với fold tiếng Việt thì **test characterization (PR4) là red-test phủ trước**. Mỗi PR trình bày theo: Title / Goal / Files to modify / Files to delete / Migration strategy / Test plan / Rollback strategy.

**Thứ tự (an toàn → rủi ro hơn):** PR1 → PR2 → PR3 → PR4 → PR5 → PR6 → PR7. PR4 (characterization) **phải merge trước** PR6/PR7 vì nó là lưới an toàn cho refactor parser/normalizer và fold tiếng Việt. Mỗi PR độc lập, app luôn xanh giữa các PR.

> ⚠️ CLAUDE.md: **không bao giờ `git push`**, **không thêm trailer `Co-Authored-By`/AI attribution** vào commit message.

> 📌 **Phụ thuộc P0 đã merge:** P0 (các commit `e2a035d..e2d7a79`) đã xóa `save_extracted_facts`/`save_raw_document` ⇒ bảng `extracted_facts`/`raw_documents` hiện **không bao giờ được ghi**. Vì vậy audit item **D3 ("đặt `extracted_facts` idempotent") bị vô hiệu hóa** — không có writer để làm idempotent. D3 được **loại khỏi P1** và gộp vào quyết định data-path ở P2 (§1 audit). Xem Self-Review.

---

## PR1 — Thêm index `knowledge_chunks(knowledge_document_id)` (D4)

**Title:** `perf(db): index knowledge_chunks.knowledge_document_id`

**Goal:** Tránh seq-scan trên 2 query lọc theo `knowledge_document_id` (`repository.py:119` `get_embedding_map_for_document`, `:151` `delete_chunks_for_document`). Thuần **bổ sung**, idempotent, không đụng code app — PR an toàn nhất.

**Files to modify:** (none — chỉ thêm 1 file migration mới)

**Files to delete:** (none)

**Migration strategy:** Thêm migration mới `db/migrations/017_knowledge_chunk_doc_index.sql`. Theo đúng convention idempotent của repo (`CREATE INDEX IF NOT EXISTS idx_<table>_<col>`, xem `016_cutoff_records.sql`). `setup_db.run_migrations()` glob + sort + chạy lần lượt ⇒ migration mới tự được áp khi `python -m db.setup_db`. Không sửa bảng cũ, không backfill.

**Test plan:**
- [ ] **Step 1 — Tạo file** `db/migrations/017_knowledge_chunk_doc_index.sql`:
  ```sql
  -- Index cho 2 truy vấn per-document trong services/knowledge/repository.py:
  --   get_embedding_map_for_document  (WHERE knowledge_document_id = %s ...)
  --   delete_chunks_for_document      (DELETE ... WHERE knowledge_document_id = %s)
  -- Trước đây chỉ có index theo (school, topic) và HNSW theo embedding ⇒ filter
  -- theo FK này phải seq-scan. Idempotent, an toàn re-run.
  CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document
      ON knowledge_chunks (knowledge_document_id);
  ```
- [ ] **Step 2 — Kiểm cú pháp SQL tĩnh** (không cần DB):
  ```bash
  python -c "import pathlib,re; s=pathlib.Path('db/migrations/017_knowledge_chunk_doc_index.sql').read_text(); assert 'IF NOT EXISTS' in s and 'knowledge_document_id' in s; print('ok')"
  ```
  Kỳ vọng: `ok`.
- [ ] **Step 3 — Áp migration trên DB dev** (cần Docker DB; chứng minh chạy sạch + idempotent re-run):
  ```bash
  docker compose up -d --wait db
  python -m db.setup_db
  python -m db.setup_db   # chạy lần 2: IF NOT EXISTS ⇒ không lỗi
  ```
  Kỳ vọng: log `✅ 017_knowledge_chunk_doc_index.sql applied`, lần 2 không lỗi.
- [ ] **Step 4 — Xác minh index tồn tại:**
  ```bash
  docker compose exec -T db psql -U postgres -d admission -c "\di idx_knowledge_chunks_document"
  ```
  Kỳ vọng: liệt kê đúng 1 index trên bảng `knowledge_chunks`.
- [ ] **Step 5 — Full suite** (integration sẽ chạy lại migration trên DB test, chứng minh không vỡ):
  `python -m pytest -q` → PASS.
- [ ] **Step 6 — Commit.**
  ```bash
  git add db/migrations/017_knowledge_chunk_doc_index.sql
  git commit -m "perf(db): index knowledge_chunks.knowledge_document_id"
  ```

**Rollback strategy:** `git revert <sha>` gỡ file migration khỏi repo. Index đã tạo trên DB không tự mất nhưng **vô hại** (chỉ là index dư). Nếu muốn dọn hẳn: `DROP INDEX IF EXISTS idx_knowledge_chunks_document;`.

---

## PR2 — Siết `max_length` cho input chat public (C2)

**Title:** `feat(web): cap chat message length to prevent abuse`

**Goal:** Endpoint `POST /{session_token}/messages` ẩn danh, public; `ChatMessageCreate.content` hiện là `str` **không giới hạn** ⇒ rủi ro DoS/đốt token. Thêm `max_length` qua Pydantic `Field` ⇒ FastAPI tự trả `422` trước khi vào handler.

**Files to modify:**
- `web/routes/chat_api.py` — thêm `Field(max_length=...)` cho `content` (def hiện tại `:15-16`).

**Files to delete:** (none)

**Migration strategy:** Đổi `content: str` → `content: str = Field(max_length=4000)`. Cận 4000 ký tự đủ cho mọi câu hỏi tư vấn thực tế (gấp ~10 lần tin nhắn dài nhất trong test/e2e), nhưng chặn payload lạm dụng. Không thêm `min_length` (tránh phá test/flow gửi chuỗi rỗng nếu có). Import `Field` từ `pydantic` (file đã import `BaseModel`).

**Test plan:**
- [ ] **Step 1 — Viết test đỏ** trong `tests/web/test_chat_session_api.py` (theo pattern `TestClient(build_app())` sẵn có):
  ```python
  def test_post_message_rejects_oversized_content():
      client = TestClient(build_app())
      response = client.post(
          "/api/sessions/session-123/messages",
          json={"content": "x" * 4001},
      )
      assert response.status_code == 422
  ```
- [ ] **Step 2 — Chạy test, kỳ vọng FAIL** (hiện chưa có giới hạn ⇒ trả 200 hoặc 500, không phải 422):
  ```bash
  python -m pytest -q tests/web/test_chat_session_api.py::test_post_message_rejects_oversized_content
  ```
  Kỳ vọng: FAIL.
- [ ] **Step 3 — Sửa model.** Trong `web/routes/chat_api.py`:
  ```python
  from pydantic import BaseModel, Field
  ...
  class ChatMessageCreate(BaseModel):
      content: str = Field(max_length=4000)
  ```
- [ ] **Step 4 — Chạy lại test, kỳ vọng PASS:**
  ```bash
  python -m pytest -q tests/web/test_chat_session_api.py::test_post_message_rejects_oversized_content
  ```
  Kỳ vọng: PASS.
- [ ] **Step 5 — Đảm bảo không vỡ đường happy** (tin nhắn bình thường vẫn 200):
  ```bash
  python -m pytest -q tests/web/test_chat_session_api.py
  python -c "import web.app; print('app ok')"
  ```
- [ ] **Step 6 — Full suite.** `python -m pytest -q` → PASS.
- [ ] **Step 7 — Commit.**
  ```bash
  git add web/routes/chat_api.py tests/web/test_chat_session_api.py
  git commit -m "feat(web): cap chat message length to prevent abuse"
  ```

**Rollback strategy:** `git revert <sha>` đưa `content` về `str` không giới hạn. Không có state/DB nào phụ thuộc.

---

## PR3 — Thêm timeout cho mọi LLM/embedding call (A2/C1)

**Title:** `fix(inference): add request timeout to Gemini client`

**Goal:** `generate_content` (`gemini_provider.py:61`) và `embed_content` (`embedder.py:46`) hiện **không có timeout** ⇒ connection treo block worker vô hạn, rotation key không bao giờ kích hoạt (audit A2/C1, mức Cao). Vá tại **1 điểm duy nhất**: client factory dùng chung của cả 2 call-site (`key_pool._default_client_factory`). Đơn giản hơn luồn timeout qua từng policy, và phủ cả provider lẫn embedder cùng lúc.

**Files to modify:**
- `ingestion/config/settings.py` — thêm setting `GEMINI_REQUEST_TIMEOUT_SECONDS` (cạnh cụm `GEMINI_*`).
- `services/inference/providers/key_pool.py` — `_default_client_factory` truyền `http_options=types.HttpOptions(timeout=...)`.

**Files to delete:** (none)

**Migration strategy:** `google-genai==1.75.0` nhận timeout (đơn vị **mili-giây**) qua `types.HttpOptions(timeout=ms)` ở cấp client. Vì `GeminiProvider` và `GeminiEmbedder` đều lấy client từ cùng `GeminiKeyPool` (factory mặc định `_default_client_factory`), chỉ cần sửa factory ⇒ mọi call thừa hưởng timeout, không đụng `_call`/`embed`. Khi treo quá hạn, SDK raise → `key_pool.call` bắt: timeout **không** phải lỗi rotatable (network) ⇒ `release` key + raise `InferenceError`; call-site đã `except InferenceError` và degrade graceful theo CLAUDE.md. Mặc định 60s (rộng cho model chậm, vẫn hữu hạn); chỉnh qua env `GEMINI_REQUEST_TIMEOUT_SECONDS`.

**Test plan:**
- [ ] **Step 1 — Viết test đỏ** `tests/services/inference/test_key_pool_timeout.py` (theo pattern monkeypatch `key_pool_module.genai.Client` đã dùng ở `test_gemini_provider.py`):
  ```python
  import services.inference.providers.key_pool as key_pool

  def test_default_client_factory_sets_request_timeout(monkeypatch):
      captured = {}

      class _SDKClient:
          def __init__(self, *, api_key, http_options=None):
              captured["api_key"] = api_key
              captured["http_options"] = http_options

      monkeypatch.setattr(key_pool.genai, "Client", _SDKClient)
      key_pool._default_client_factory("k-1")

      assert captured["api_key"] == "k-1"
      assert captured["http_options"] is not None
      # google-genai dùng mili-giây; mặc định 60s = 60000ms.
      assert captured["http_options"].timeout == 60_000
  ```
- [ ] **Step 2 — Chạy test, kỳ vọng FAIL** (factory hiện không truyền `http_options`):
  ```bash
  python -m pytest -q tests/services/inference/test_key_pool_timeout.py
  ```
  Kỳ vọng: FAIL (`http_options is None` hoặc `TypeError` nếu fake không nhận kwarg — chứng minh chưa truyền).
- [ ] **Step 3 — Thêm setting.** Trong `ingestion/config/settings.py`, ngay sau `GEMINI_KEY_COOLDOWN_SECONDS`:
  ```python
  # Hard timeout (giây) cho mỗi lời gọi Gemini generate/embed. Không có timeout
  # thì connection treo sẽ giữ worker vô hạn và rotation key không bao giờ kích hoạt.
  GEMINI_REQUEST_TIMEOUT_SECONDS = float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", 60))
  ```
- [ ] **Step 4 — Sửa factory.** Trong `services/inference/providers/key_pool.py`:
  ```python
  from google import genai
  from google.genai import types
  ...
  from ingestion.config.settings import (
      GEMINI_KEY_COOLDOWN_SECONDS,
      GEMINI_REQUEST_TIMEOUT_SECONDS,
  )
  ...
  def _default_client_factory(api_key: str):
      # http_options.timeout tính bằng mili-giây (google-genai 1.75.0).
      return genai.Client(
          api_key=api_key,
          http_options=types.HttpOptions(
              timeout=int(GEMINI_REQUEST_TIMEOUT_SECONDS * 1000)
          ),
      )
  ```
- [ ] **Step 5 — Chạy lại test, kỳ vọng PASS:**
  ```bash
  python -m pytest -q tests/services/inference/test_key_pool_timeout.py
  ```
  Kỳ vọng: PASS.
- [ ] **Step 6 — Regression provider + embedder** (fake client của 2 suite này nhận `**kwargs`/`api_key`; nếu fake nào ký rõ `__init__(self,*,api_key)` mà chưa nhận `http_options` thì cập nhật fake cho khớp constructor mới):
  ```bash
  python -m pytest -q tests/services/inference/test_gemini_provider.py tests/ingestion/knowledge/test_embedder.py
  ```
  Kỳ vọng: PASS.
- [ ] **Step 7 — Full suite + smoke import.**
  ```bash
  python -c "import services.inference.providers.key_pool; print('ok')"
  python -m pytest -q
  ```
  Kỳ vọng: `ok` + PASS.
- [ ] **Step 8 — Commit.**
  ```bash
  git add ingestion/config/settings.py services/inference/providers/key_pool.py tests/services/inference/test_key_pool_timeout.py
  git commit -m "fix(inference): add request timeout to Gemini client"
  ```

**Rollback strategy:** `git revert <sha>` — gỡ timeout (về hành vi treo cũ). Không state nào khác đổi. Nếu chỉ cần nới timeout tạm: set env `GEMINI_REQUEST_TIMEOUT_SECONDS` cao hơn, không cần revert code.

---

## PR4 — Test characterization cho normalizer/mapper/parser (§7)

**Title:** `test(ingestion): characterization tests for normalization & hust parser helpers`

**Goal:** Các module logic lõi (`normalizer`, `quota_parser`, các `*_mapper`, helper thuần của `hust_program_parser`) **chưa có test** ⇒ refactor mù. Viết test **pin hành vi hiện tại** (kể cả quirk) để mở khóa PR6/PR7 an toàn. Thuần **bổ sung test**, không đụng source ⇒ rủi ro chỉ là "test viết sai", không phá runtime.

**Files to modify:** (none — chỉ thêm file test)

**Files to delete:** (none)

**Migration strategy:** Đặt test theo convention sẵn có (`tests/ingestion/test_<module>.py`, monkeypatch `_load_dict`/`_load_all` như `tests/ingestion/test_program_mapper.py`). Bắt đầu từ **hàm thuần** (quota_parser, helper hust, các mapper với dict giả) — rẻ, không cần DB/mạng. **Quan trọng:** pin *hành vi thực tế đang chạy*, không pin "hành vi mong muốn" (vd quirk `đ` trong `_normalize_for_match`, và quirk regex của `parse_quota`). Nếu một assertion bất ngờ → chạy hàm in kết quả thật rồi chốt theo đó (đó chính là giá trị của characterization).

**Test plan:**
- [ ] **Step 1 — `tests/ingestion/test_quota_parser.py`** (pin cả quirk: nhánh `approximate` thực tế không bao giờ chạy khi có chữ số vì `exact_match` bắt trước):
  ```python
  from ingestion.normalization.quota_parser import parse_quota

  def test_parse_quota_none_returns_none():
      assert parse_quota(None) is None
      assert parse_quota("") is None

  def test_parse_quota_pure_digits_is_exact():
      q = parse_quota("300")
      assert q.value == 300 and q.quota_type == "exact"

  def test_parse_quota_range():
      q = parse_quota("khoảng 200-300")
      assert q.min_value == 200 and q.max_value == 300 and q.quota_type == "range"

  def test_parse_quota_with_label_is_exact():
      q = parse_quota("300 chỉ tiêu")
      assert q.value == 300 and q.quota_type == "exact"

  def test_parse_quota_khoang_with_number_is_exact_not_approximate():
      # QUIRK pinned: exact_match (\d+) bắt trước nhánh "khoảng" ⇒ exact, KHÔNG approximate.
      q = parse_quota("khoảng 250")
      assert q.value == 250 and q.quota_type == "exact"

  def test_parse_quota_unknown_keyword():
      assert parse_quota("chưa công bố").quota_type == "unknown"

  def test_parse_quota_no_match_falls_back_unknown():
      assert parse_quota("tuyển sinh").quota_type == "unknown"
  ```
- [ ] **Step 2 — `tests/ingestion/test_hust_parser_helpers.py`** (pin quirk `đ`: `_normalize_for_match` KHÔNG map `đ→d`, lọc combining mark nên `đ` sống sót — đây là bug PR7 sẽ sửa, nhưng giờ pin nguyên trạng để bắt được thay đổi):
  ```python
  from ingestion.parsers.hust_program_parser import _normalize_for_match

  def test_normalize_for_match_strips_accents_and_lowercases():
      assert _normalize_for_match("Xét tuyển") == "xet tuyen"
      assert _normalize_for_match("ĐIỀU KIỆN") == _normalize_for_match("ĐIỀU KIỆN")

  def test_normalize_for_match_does_not_collapse_internal_whitespace():
      # QUIRK pinned: helper hust chỉ .lower().strip(), KHÔNG gộp khoảng trắng trong.
      assert _normalize_for_match("xet   tuyen") == "xet   tuyen"

  def test_normalize_for_match_keeps_d_stroke():
      # QUIRK pinned (BUG): "đ" KHÔNG được map sang "d" (PR7 sẽ đổi giá trị này).
      out = _normalize_for_match("đại học")
      assert out == "đai hoc"
  ```
- [ ] **Step 3 — `tests/ingestion/test_subject_combination_mapper.py`** (dict giả qua monkeypatch `_load_dict`):
  ```python
  import ingestion.normalization.subject_combination_mapper as scm

  _FAKE = {
      "A00": {"subjects": ["Toán", "Lý", "Hoá"], "description": "Toán, Lý, Hoá"},
      "D01": {"subjects": ["Toán", "Văn", "Anh"], "description": "Toán, Văn, Anh"},
  }

  def test_map_combinations_by_code(monkeypatch):
      monkeypatch.setattr(scm, "_load_dict", lambda: _FAKE)
      result = scm.map_combinations(["A00", "D01"])
      assert [c.code for c in result] == ["A00", "D01"]
      assert result[0].subjects == ["Toán", "Lý", "Hoá"]

  def test_map_combinations_none_or_empty(monkeypatch):
      monkeypatch.setattr(scm, "_load_dict", lambda: _FAKE)
      assert scm.map_combinations(None) == []
      assert scm.map_combinations([]) == []
  ```
  > Trước khi chốt assertion, chạy `python -c "import ingestion.normalization.subject_combination_mapper as m; print(m.map_combinations(['A00']))"` (với dict thật) để xác nhận shape `SubjectCombination` (`.code`, `.subjects`) khớp — sửa assertion theo output thật nếu lệch.
- [ ] **Step 4 — `tests/ingestion/test_method_mapper.py` & `tests/ingestion/test_combo_method_mapper.py`** (monkeypatch `_load_all`/`_load_rules` với dữ liệu giả nhỏ; pin: exact/substring match, fallback trả raw, regex-rule first-match-wins):
  ```python
  # test_method_mapper.py
  import ingestion.normalization.method_mapper as mm

  _FAKE = {"_shared": {"thpt_score": {"canonical_name": "Xét điểm thi TN THPT",
                                       "aliases": ["xet diem thi", "ket qua thi"]}}}

  def test_map_method_alias_hits_code(monkeypatch):
      monkeypatch.setattr(mm, "_load_all", lambda: _FAKE)
      monkeypatch.setattr(mm, "_load_dict", lambda school_id="": _FAKE["_shared"])
      assert mm.map_method("Xét điểm thi tốt nghiệp", school_id="hust") == "thpt_score"

  def test_map_method_unknown_returns_none_or_raw(monkeypatch):
      monkeypatch.setattr(mm, "_load_all", lambda: _FAKE)
      monkeypatch.setattr(mm, "_load_dict", lambda school_id="": _FAKE["_shared"])
      out = mm.map_method("phương thức lạ hoắc", school_id="hust")
      assert out is None or isinstance(out, str)  # chốt lại theo output thật ở Step 6
  ```
  ```python
  # test_combo_method_mapper.py
  import ingestion.normalization.combo_method_mapper as cmm

  _FAKE_RULES = {"_shared": {"rules": [
      {"combo_pattern": r"^K0\d$", "method_code": "competency_test", "description": "DGTD"},
  ]}}

  def test_infer_methods_first_rule_match(monkeypatch):
      monkeypatch.setattr(cmm, "_load_rules", lambda: _FAKE_RULES)
      assert "competency_test" in cmm.infer_methods_from_combos(["K01"], school_id="hust")

  def test_infer_methods_no_match_empty(monkeypatch):
      monkeypatch.setattr(cmm, "_load_rules", lambda: _FAKE_RULES)
      assert cmm.infer_methods_from_combos(["A00"], school_id="hust") == []
  ```
  > **Trước khi chốt**, chạy thật từng hàm với dict giả ở trên qua `python -c "..."` để lấy output đúng (chữ ký `_load_dict`/`_load_all` đã verify trong audit) rồi sửa assertion cho khớp — đây là characterization, giá trị nằm ở việc *chốt đúng hành vi thật*.
- [ ] **Step 5 — `tests/ingestion/test_normalizer.py`** (orchestrator — dựng `ExtractedAdmissionFact` tối thiểu, monkeypatch các mapper con để cô lập, assert `normalize_fact` ráp đúng các trường):
  ```python
  from ingestion.models.pipeline_models import ExtractedAdmissionFact, SourceReference
  import ingestion.normalization.normalizer as nz

  def _fact():
      return ExtractedAdmissionFact(
          school_name="Đại học X", admission_year=2025,
          program_name="Khoa học Máy tính", program_code="IT1",
          admission_method_raw="Xét điểm THPT",
          subject_combinations_raw=["A00"], quota_raw="300",
          source_reference=SourceReference(source_id="s", source_url="http://e.com",
                                           school_id="hust", trust_level=5),
          confidence_score=0.8,
      )

  def test_normalize_fact_passes_through_core_fields():
      rec = nz.normalize_fact(_fact(), school_id="hust")
      assert rec.admission_year == 2025
      assert rec.quota is not None and rec.quota.value == 300
  ```
  > Chạy thật một lần để xác nhận tên field của `NormalizedAdmissionRecord` (`.quota`, `.admission_year`...) trước khi chốt — sửa theo `pipeline_models.py` thật nếu lệch.
- [ ] **Step 6 — Chạy toàn bộ test mới, sửa assertion theo output thật:**
  ```bash
  python -m pytest -q tests/ingestion/test_quota_parser.py tests/ingestion/test_hust_parser_helpers.py \
    tests/ingestion/test_subject_combination_mapper.py tests/ingestion/test_method_mapper.py \
    tests/ingestion/test_combo_method_mapper.py tests/ingestion/test_normalizer.py
  ```
  Kỳ vọng: tất cả PASS (sau khi chốt giá trị thật). Đây là baseline characterization.
- [ ] **Step 7 — Full suite.** `python -m pytest -q` → PASS.
- [ ] **Step 8 — Commit.**
  ```bash
  git add tests/ingestion/test_quota_parser.py tests/ingestion/test_hust_parser_helpers.py tests/ingestion/test_subject_combination_mapper.py tests/ingestion/test_method_mapper.py tests/ingestion/test_combo_method_mapper.py tests/ingestion/test_normalizer.py
  git commit -m "test(ingestion): characterization tests for normalization & hust parser helpers"
  ```

**Rollback strategy:** `git revert <sha>` xóa các file test. Không đụng source ⇒ rollback tuyệt đối vô hại. (Lưu ý: revert PR4 sẽ gỡ lưới an toàn cho PR6/PR7 — không revert nếu PR7 đã merge.)

---

## PR5 — Trích `services/formatting.py` cho `_fmt_num`/`_program_label` (§4.4)

**Title:** `refactor(services): extract shared formatting helpers`

**Goal:** `reasoning_service.py:5` import **private** `_fmt_num`/`_program_label` từ `explanation_service` ⇒ coupling vào nội bộ module khác (2 consumer ⇒ abstraction chính đáng). Trích sang `services/formatting.py`. Bảo toàn hành vi tuyệt đối: chỉ **dời định nghĩa + đổi import**, không sửa thân hàm, không sửa call-site.

**Files to modify:**
- `services/explanation_service.py` — xóa 2 def `_fmt_num` (`:90-94`), `_program_label` (`:97-101`); thêm import re-bind.
- `services/reasoning_service.py` — đổi import (`:5`) trỏ sang module mới.

**Files to delete:** (none)

**Migration strategy:** Tạo `services/formatting.py` với 2 hàm **public** (bỏ underscore: `fmt_num`, `program_label`) — y nguyên thân hàm. Tại 2 consumer, import-with-alias để **không phải sửa call-site nào** (giữ diff tối thiểu & rủi ro thấp nhất):
- `explanation_service.py`: `from services.formatting import fmt_num as _fmt_num, program_label as _program_label` (giữ 9 call-site nội bộ dùng `_fmt_num`/`_program_label` nguyên vẹn).
- `reasoning_service.py`: đổi `from services.explanation_service import _fmt_num, _program_label` → `from services.formatting import fmt_num as _fmt_num, program_label as _program_label`.

Không tạo shim trong `explanation_service` cho consumer ngoài vì chỉ `reasoning_service` import (audit đã xác minh không consumer khác).

**Test plan:**
- [ ] **Step 1 — Tạo `services/formatting.py`** (copy verbatim từ `explanation_service`, đổi tên public; `program_label` cần type `CandidateProgram`):
  ```python
  from typing import Any

  from agents.models import CandidateProgram


  def fmt_num(value: Any) -> str:
      """27.0 -> '27', 25.75 -> '25.75'."""
      if isinstance(value, float) and value.is_integer():
          return str(int(value))
      return str(value)


  def program_label(candidate: CandidateProgram) -> str:
      """Tên ngành hiển thị: program_name_raw (tên thực của trường) ưu tiên,
      fallback program_name (canonical) khi raw rỗng/null."""
      raw = (candidate.program_name_raw or "").strip()
      return raw or candidate.program_name
  ```
  > Xác minh đường import `CandidateProgram` khớp `explanation_service.py` hiện tại (cùng `from agents.models import ...`). Nếu P2 đã move sang `domain.models` thì dùng đường mới — kiểm `git grep "import CandidateProgram" services/explanation_service.py` trước.
- [ ] **Step 2 — Sửa `explanation_service.py`:** xóa 2 def, thêm ngay sau khối import hiện có:
  ```python
  from services.formatting import fmt_num as _fmt_num, program_label as _program_label
  ```
- [ ] **Step 3 — Sửa `reasoning_service.py:5`:**
  ```python
  from services.formatting import fmt_num as _fmt_num, program_label as _program_label
  ```
- [ ] **Step 4 — Smoke import + chứng minh không còn def chết:**
  ```bash
  python -c "import services.formatting, services.explanation_service, services.reasoning_service; print('ok')"
  git grep -n "def _fmt_num\|def _program_label" -- services/
  ```
  Kỳ vọng: `ok`; lệnh grep **không in dòng nào** (2 def đã chuyển hết sang `formatting.py` dưới tên public).
- [ ] **Step 5 — Test 2 agent dùng các helper này** (phủ gián tiếp, audit xác nhận 19+22 test):
  ```bash
  python -m pytest -q tests/agents/test_explanation_agent.py tests/agents/test_reasoning_agent.py
  ```
  Kỳ vọng: PASS (chứng minh format đầu ra không đổi).
- [ ] **Step 6 — Full suite.** `python -m pytest -q` → PASS.
- [ ] **Step 7 — Commit.**
  ```bash
  git add services/formatting.py services/explanation_service.py services/reasoning_service.py
  git commit -m "refactor(services): extract shared formatting helpers"
  ```

**Rollback strategy:** `git revert <sha>` đưa 2 def về `explanation_service` và import cũ ở `reasoning_service`. Thuần dời code, không state ⇒ an toàn.

---

## PR6 — Gom `_cursor` + `_vector_literal` vào `services/db/` (§2.3/2.7)

**Title:** `refactor(db): consolidate cursor & vector-literal helpers`

**Goal:** `_cursor` copy-paste 4 bản trong `services/` + `_vector_literal` trùng 2 nơi. Gom về 1 module `services/db/` ⇒ 1 nơi sửa logic transaction, bớt drift. **Bảo toàn hành vi tuyệt đối** (commit/rollback/close y hệt); được phủ bởi test repository sẵn có.

> Phạm vi P1 **chỉ gom 2 helper trong `services/`**. *Cố tình KHÔNG động* tới: `ingestion/storage/db_connection.py::get_cursor` (convention khác — `commit=True` mặc định, dùng `get_connection()` module-level) và 3 connection-factory (`chat/db.py`, `knowledge/db.py`, `setup_db.py` inline) — gom factory cắt ngang ranh giới ingestion/services + `DB_CONFIG`, rủi ro cao hơn ⇒ để lại như follow-up nhỏ (xem Self-Review). Giữ PR này thuần & dễ review.

**Files to modify:**
- `services/chat/repository.py` — `_cursor` method (`:14-35`) → delegate.
- `services/tracing/trace_repository.py` — `_cursor` method (`:13-29`) → delegate.
- `services/knowledge/repository.py` — bỏ `_cursor` (`:30-46`) + `_vector_literal` (`:24-27`), import từ `services.db`.
- `services/profile/major_catalog_repository.py` — bỏ `_cursor` (`:21-37`) + `_vector_literal` (`:15-18`), import từ `services.db`.

**Files to delete:** (none)

**Migration strategy:** Tạo package `services/db/` với `cursor(connection_factory, commit=False)` (bản module-level, chữ ký khớp 2 copy module-func sẵn có) và `vector_literal(embedding)`.
- 2 copy **module-func** (`knowledge`, `major_catalog`): xóa def local, thêm `from services.db import cursor as _cursor, vector_literal as _vector_literal` ⇒ **mọi call-site `_cursor(self.connection_factory, ...)` / `_vector_literal(...)` giữ nguyên**.
- 2 copy **instance-method** (`chat`, `tracing`): giữ method `_cursor` nhưng đổi thân thành delegate (call-site `with self._cursor(...)` giữ nguyên):
  ```python
  def _cursor(self, commit: bool = False):
      return cursor(self.connection_factory, commit=commit)
  ```
  (`cursor(...)` trả về context manager dùng chung; `with self._cursor(...) as cur` hoạt động y hệt.)

Hành vi `cursor` chung sao chép **chính xác** bản đang dùng (commit khi `commit=True`, rollback + re-raise khi exception, `cur.close()` rồi `conn.close()` trong finally). `commit=False` mặc định khớp bản services (KHÁC `get_cursor` ingestion mặc định `True` — lý do nữa để không trộn).

**Test plan:**
- [ ] **Step 1 — Baseline xanh** (chứng minh trạng thái tốt trước khi dời):
  ```bash
  python -m pytest -q tests/services/chat/test_repository.py tests/services/knowledge/test_repository.py tests/services/tracing/test_trace_repository.py tests/services/profile/
  ```
  Kỳ vọng: PASS.
- [ ] **Step 2 — Tạo `services/db/__init__.py`:**
  ```python
  """Shared DB helpers: 1 cursor context manager + pgvector literal builder.

  Gom từ 4 bản _cursor copy-paste + 2 bản _vector_literal trong services/.
  Hành vi y hệt bản cũ: commit khi commit=True, rollback + re-raise khi lỗi,
  cur.close() rồi conn.close() trong finally.
  """
  from contextlib import contextmanager
  from typing import Optional


  @contextmanager
  def cursor(connection_factory, commit: bool = False):
      conn = connection_factory()
      try:
          cur = conn.cursor()
          try:
              yield cur
              if commit:
                  conn.commit()
          except Exception:
              conn.rollback()
              raise
          finally:
              cur.close()
      finally:
          conn.close()


  def vector_literal(embedding) -> Optional[str]:
      if embedding is None:
          return None
      return "[" + ",".join(str(float(x)) for x in embedding) + "]"
  ```
- [ ] **Step 3 — Sửa `knowledge/repository.py`:** xóa def `_cursor` (`:30-46`) và `_vector_literal` (`:24-27`); thêm vào khối import:
  ```python
  from services.db import cursor as _cursor, vector_literal as _vector_literal
  ```
  (Tất cả call-site `_cursor(self.connection_factory, ...)` / `_vector_literal(...)` không đổi.)
- [ ] **Step 4 — Sửa `profile/major_catalog_repository.py`:** y hệt Step 3 (xóa 2 def `:15-18`, `:21-37`; thêm cùng dòng import).
- [ ] **Step 5 — Sửa `chat/repository.py`:** thêm `from services.db import cursor`, đổi thân method `_cursor` thành delegate (xóa docstring dài cũ, hoặc giữ làm comment):
  ```python
  from services.db import cursor
  ...
      def _cursor(self, commit: bool = False):
          # Delegate sang helper dùng chung (services/db). Hành vi không đổi.
          return cursor(self.connection_factory, commit=commit)
  ```
- [ ] **Step 6 — Sửa `tracing/trace_repository.py`:** y hệt Step 5.
- [ ] **Step 7 — Smoke import + xác minh hết def trùng:**
  ```bash
  python -c "import services.db, services.chat.repository, services.tracing.trace_repository, services.knowledge.repository, services.profile.major_catalog_repository; print('ok')"
  git grep -n "def _vector_literal" -- services/    # kỳ vọng: 0 dòng (đã về services/db)
  git grep -n "def _cursor" -- services/             # kỳ vọng: chỉ còn 2 delegate (chat, tracing)
  ```
- [ ] **Step 8 — Chạy lại test repository** (lưới chính của PR này — fake `connection_factory=lambda: conn` vẫn hoạt động):
  ```bash
  python -m pytest -q tests/services/chat/test_repository.py tests/services/knowledge/test_repository.py tests/services/tracing/test_trace_repository.py tests/services/profile/
  ```
  Kỳ vọng: PASS (giống Step 1).
- [ ] **Step 9 — Full suite.** `python -m pytest -q` → PASS.
- [ ] **Step 10 — Commit.**
  ```bash
  git add services/db/__init__.py services/chat/repository.py services/tracing/trace_repository.py services/knowledge/repository.py services/profile/major_catalog_repository.py
  git commit -m "refactor(db): consolidate cursor & vector-literal helpers"
  ```

**Rollback strategy:** `git revert <sha>` khôi phục 4 `_cursor` + 2 `_vector_literal` cũ và xóa `services/db/`. Vì hành vi giữ nguyên và call-site không đổi, revert sạch. Không migration/DB.

---

## PR7 — Gom 1 util `vietnamese_fold()`, route các nơi qua đó (§2.2)

**Title:** `refactor(text): unify Vietnamese diacritic folding`

**Goal:** Routine "bỏ dấu, lowercase, gộp khoảng trắng" được viết 4 bản **lệch nhau ở `đ`/whitespace** ⇒ rủi ro matching sai (đặc biệt `_normalize_for_match` của HUST **không map `đ`** ⇒ "đ" sống sót). Trích 1 util `vietnamese_fold(text)` (nguồn chân lý = `profile_service.normalize_text`), route các nơi qua đó. **Đây là PR rủi ro cao nhất P1** vì sửa hành vi matching ⇒ **bắt buộc PR4 (characterization) đã merge**.

> ⚠️ **GATE phụ thuộc:** Chỉ làm PR7 sau khi PR4 xanh trên nhánh. PR4 pin quirk `đ`/whitespace của `_normalize_for_match` — PR7 sẽ **cố ý đổi** các giá trị đó; cập nhật chính các test characterization đó cho khớp hành vi mới (kèm comment "fixed by PR7").

**Files to modify:**
- `services/profile_service.py` — `normalize_text` (`:41-47`) → delegate sang util mới (giữ tên public, 10 call-site nguyên vẹn).
- `ingestion/parsers/vnu_uet_admission_parser.py` — `_normalize` (`:52-60`) → delegate.
- `ingestion/parsers/hust_program_parser.py` — `_normalize_for_match` (`:75-82`) → delegate (**đổi hành vi: thêm `đ→d` + gộp whitespace**).
- `tests/ingestion/test_hust_parser_helpers.py` — cập nhật 2 assertion quirk thành hành vi mới.

**Files to delete:** (none)

**Migration strategy:** Tạo `services/text_utils.py::vietnamese_fold(text)` = bản canonical của `normalize_text` (map `đ→d`/`Đ→D` trước, NFKD, ascii-ignore, lower, gộp whitespace bằng `" ".join(split())`).
- `profile_service.normalize_text`: đổi thân thành `return vietnamese_fold(text)` (hành vi **giống hệt** — nó vốn là nguồn chân lý ⇒ 10 call-site + test `test_profile_service.py` không đổi kết quả).
- `vnu_uet `_normalize`: đổi thành `return vietnamese_fold(text)`. Khác biệt cũ (lọc combining vs ascii-ignore; `translate` đ) cho **cùng kết quả** trên text Việt+Latin; whitespace cũ `re.sub(\s+," ").strip()` = gộp, khớp canonical. → phủ bởi `tests/ingestion/test_vnu_uet_admission_parser.py`.
- `hust `_normalize_for_match`: đổi thành `return vietnamese_fold(text)`. **Thay đổi hành vi có chủ đích:** giờ `đ→d` (sửa bug) + gộp whitespace trong. → phủ bởi PR4 helper test (cập nhật) + characterization parser.

**KHÔNG động** `ingestion/main.py::_ascii_text` (`:205-209`): contract khác hẳn (console-only, **không** lower, **không** gộp whitespace — giữ tên trường để in) ⇒ route qua `vietnamese_fold` sẽ đổi output hiển thị. Ghi chú loại trừ trong commit body.

**Test plan:**
- [ ] **Step 0 — GATE:** xác nhận PR4 đã merge & xanh (`git log --oneline | grep characterization`). Nếu chưa → dừng, làm PR4 trước.
- [ ] **Step 1 — Tạo `services/text_utils.py`:**
  ```python
  import unicodedata


  def vietnamese_fold(text: str) -> str:
      """Bỏ dấu + lowercase + gộp khoảng trắng cho keyword matching tiếng Việt.

      Nguồn chân lý duy nhất (gom từ 4 bản lệch nhau, audit §2.2). "đ"/"Đ"
      (U+0111/U+0110) không có NFKD decomposition nên phải map sang d/D TRƯỚC,
      nếu không ascii-strip sẽ nuốt mất ("điểm" -> "iem").
      """
      text = text.replace("đ", "d").replace("Đ", "D")
      normalized = unicodedata.normalize("NFKD", text)
      ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
      return " ".join(ascii_text.lower().split())
  ```
- [ ] **Step 2 — Viết test cho util mới** `tests/services/test_text_utils.py`:
  ```python
  from services.text_utils import vietnamese_fold

  def test_fold_maps_d_stroke():
      assert vietnamese_fold("Đại học Đà Nẵng") == "dai hoc da nang"

  def test_fold_strips_accents_and_lowercases():
      assert vietnamese_fold("Xét Tuyển") == "xet tuyen"

  def test_fold_collapses_whitespace():
      assert vietnamese_fold("  xet   tuyen \n thang ") == "xet tuyen thang"
  ```
  Chạy: `python -m pytest -q tests/services/test_text_utils.py` → PASS.
- [ ] **Step 3 — Route `profile_service.normalize_text`** (`:41-47`) → delegate; giữ comment giải thích:
  ```python
  from services.text_utils import vietnamese_fold
  ...
  def normalize_text(text: str) -> str:
      return vietnamese_fold(text)
  ```
  Chạy `python -m pytest -q tests/services/test_profile_service.py` → PASS (kết quả không đổi).
- [ ] **Step 4 — Route `vnu_uet_admission_parser._normalize`** (`:52-60`) → delegate:
  ```python
  from services.text_utils import vietnamese_fold
  ...
  def _normalize(text: str) -> str:
      return vietnamese_fold(text)
  ```
  Chạy `python -m pytest -q tests/ingestion/test_vnu_uet_admission_parser.py` → PASS. **Nếu FAIL** (khác biệt combining-vs-ascii bộc lộ) → đó là tín hiệu hành vi thật khác; điều tra bằng systematic-debugging, KHÔNG ép xanh. Fallback an toàn: giữ `_normalize` cũ cho vnu (chỉ gom hust + profile) và ghi chú lại.
- [ ] **Step 5 — Route `hust._normalize_for_match`** (`:75-82`) → delegate (đổi hành vi có chủ đích):
  ```python
  from services.text_utils import vietnamese_fold
  ...
  def _normalize_for_match(text: str) -> str:
      """Normalize tiếng Việt cho keyword matching ("Xét tuyển" -> "xet tuyen")."""
      return vietnamese_fold(text)
  ```
- [ ] **Step 6 — Cập nhật test characterization PR4** (`tests/ingestion/test_hust_parser_helpers.py`) cho hành vi mới:
  ```python
  def test_normalize_for_match_now_maps_d_stroke():
      # FIXED by PR7: "đ" -> "d" (trước đây giữ nguyên "đ").
      assert _normalize_for_match("đại học") == "dai hoc"

  def test_normalize_for_match_now_collapses_whitespace():
      # FIXED by PR7: gộp khoảng trắng trong (trước đây giữ nguyên).
      assert _normalize_for_match("xet   tuyen") == "xet tuyen"
  ```
  (Xóa/điều chỉnh 2 test quirk cũ `test_normalize_for_match_keeps_d_stroke` và `..._does_not_collapse_internal_whitespace`.)
- [ ] **Step 7 — Chạy characterization parser HUST + suite ingestion** (lưới chính: chứng minh thay đổi `đ` không làm hỏng parse thật):
  ```bash
  python -m pytest -q tests/ingestion/
  ```
  Kỳ vọng: PASS. Nếu một test parse HUST đổi kết quả → đối chiếu thủ công xem có phải cải thiện đúng (đ được match) hay regression; chốt theo đúng đắn nghiệp vụ.
- [ ] **Step 8 — Smoke import + xác minh không còn fold trùng:**
  ```bash
  python -c "import services.text_utils, services.profile_service, ingestion.parsers.vnu_uet_admission_parser, ingestion.parsers.hust_program_parser; print('ok')"
  ```
- [ ] **Step 9 — Full suite.** `python -m pytest -q` → PASS.
- [ ] **Step 10 — Commit.**
  ```bash
  git add services/text_utils.py tests/services/test_text_utils.py services/profile_service.py ingestion/parsers/vnu_uet_admission_parser.py ingestion/parsers/hust_program_parser.py tests/ingestion/test_hust_parser_helpers.py
  git commit -m "refactor(text): unify Vietnamese diacritic folding"
  ```

**Rollback strategy:** `git revert <sha>` khôi phục 3 bản fold cũ + `services/text_utils.py` biến mất + test characterization về quirk cũ. Vì PR4 đã pin hành vi cũ, sau revert suite vẫn nhất quán. Nếu chỉ HUST gây regression → biến thể tối thiểu: revert riêng phần `hust._normalize_for_match`, giữ gom `profile`+`vnu`.

---

## Self-Review (đối chiếu với §9 P1 của audit)

| Hạng mục P1 trong audit (§9) | PR phủ | Ghi chú |
|---|---|---|
| (ưu tiên) Thêm timeout LLM call (A2/C1) | **PR3** | Vá tại client factory dùng chung ⇒ phủ cả provider + embedder |
| `max_length` cho `ChatMessageCreate.content` (C2) | **PR2** | `Field(max_length=4000)` ⇒ FastAPI auto-422 |
| Gom `vietnamese_fold()`, route các nơi (§2.2) | **PR7** | Rủi ro cao nhất; gate sau PR4; `_ascii_text` cố ý loại trừ |
| Gom `_cursor`+`_vector_literal` vào `services/db/` (§2.3/2.7) | **PR6** | Factory connection (§2.6) **deferred** — xem dưới |
| Trích `services/formatting.py` (§4.4) | **PR5** | Import-alias ⇒ 0 call-site đổi |
| Đặt `extracted_facts` idempotent (D3) | **LOẠI** | Superseded bởi P0: writer đã bị xóa ⇒ bảng không được ghi. Gộp vào quyết định data-path P2 (§1) |
| Index `knowledge_chunks(knowledge_document_id)` (D4) | **PR1** | Migration `017`, idempotent |
| Test characterization normalizer/mapper/extractor (§7) | **PR4** | Là gate cho PR6/PR7; phủ quota/mapper/hust helper/normalizer |

**Quyết định cố ý để lại (không làm trong P1):**
- **D3 `extracted_facts` idempotent** — vô hiệu do P0 đã xóa writer; thuộc quyết định data-path P2 (bật lại đường ghi facts *hay* đơn giản hóa `evidence_agent` LEFT JOIN).
- **Connection-factory consolidation (§2.6)** — 3 factory + 5 inline trong `setup_db.py` cắt ngang ranh giới ingestion/services + phụ thuộc `DB_CONFIG`; rủi ro/blast-radius cao hơn 2 helper thuần ⇒ tách follow-up nhỏ riêng (không nhồi vào PR6 để giữ PR review được).
- **`ingestion/storage/db_connection.py::get_cursor`** — convention khác (`commit=True` mặc định, `get_connection()` module-level); trộn vào `services/db.cursor` (`commit=False`) sẽ đổi hành vi mặc định ⇒ để nguyên.
- **Test characterization cho `admission_extractor`/`pdf_parser`/`document_router`** (§7) — PR4 ưu tiên các hàm thuần rẻ (mở khóa PR6/PR7); phần extractor (LLM fallback) + parser I/O nặng để lại cùng P2 khi migrate `llm_extractor` qua gateway (§2.1).

**Nguyên tắc đã tuân thủ:** không big-bang; mỗi PR nhỏ + revert độc lập; app xanh giữa mỗi PR (smoke import + full suite); ưu tiên đơn giản hóa hơn trừu tượng hóa (PR3 vá 1 điểm thay vì luồn policy; PR5/PR6 import-alias + delegate ⇒ 0 call-site đổi); không đụng public API đang dùng (`normalize_text`, các method repository, route giữ chữ ký); thứ tự an toàn → rủi ro với PR4 làm lưới an toàn trước PR6/PR7.
