# Lộ trình tái cấu trúc P2 — Admission Advisory System

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans để thực thi plan này theo từng task. Các bước dùng cú pháp checkbox (`- [ ]`) để theo dõi.

**Goal:** Thực hiện toàn bộ nhóm P2 ("kiến trúc rủi ro trung bình") của báo cáo audit `2026-06-16-architecture-audit.md` thành 10 PR nhỏ, mỗi PR review được độc lập và giữ ứng dụng luôn chạy.

**Architecture:** Mỗi PR là một thay đổi cơ học hoặc trích-xuất nhỏ; ưu tiên **xóa hơn viết lại**, **đơn giản hóa hơn trừu tượng hóa**; **bảo toàn mọi public API** (dùng shim re-export khi di chuyển module). Không có big-bang: thứ tự từ an toàn nhất → rủi ro nhất, mỗi PR commit riêng và chạy được pytest xanh trước khi sang PR kế.

**Tech Stack:** Python 3, Pydantic v2, FastAPI, psycopg2 + pgvector, `google-genai` (SDK mới), LangGraph, pytest + monkeypatch/fake.

---

## Nguyên tắc chung cho mọi PR

- **Không `git push`** (theo CLAUDE.md). Chỉ `git commit` khi được yêu cầu, **không** trailer `Co-Authored-By`.
- Mỗi PR: chạy `python -m pytest -q` xanh trước khi commit. Trên Linux dùng `.venv/bin/python -m pytest -q`; trên Windows dùng `.\.venv\Scripts\python.exe -m pytest -q`. Plan dưới đây viết lệnh dạng `pytest` cho gọn.
- Test integration cần Docker DB (`docker compose up -d --wait db`); nếu không có Docker, các test đó tự skip — vẫn phải để unit test xanh.
- **Rollback mặc định cho mọi PR:** vì mỗi PR là 1 commit độc lập, rollback = `git revert <commit>` (hoặc `git reset --hard HEAD~1` nếu chưa hợp nhất). Các PR di chuyển file đều để lại shim nên revert không làm gãy import bên thứ ba. Phần "Rollback strategy" của từng PR chỉ ghi thêm lưu ý đặc thù (ví dụ migration cần script down).

## Bảng tổng quan thứ tự (an toàn → rủi ro)

| PR | Tên | Mục audit | Rủi ro | Phụ thuộc |
|----|-----|-----------|--------|-----------|
| 1 | Xóa bảng chết `discovered_resources` + đơn giản hóa query evidence | §1, §4.5 | Rất thấp | — |
| 2 | Move `agents/models.py` → `domain/models.py` + shim | §4.1 | Thấp (cơ học) | — |
| 3 | Move `GeminiEmbedder` → `services/inference/embedder.py` + shim | §4.8 | Thấp (cơ học) | — |
| 4 | `ConflictEvidenceRepository` + `CutoffRepository` (gói SQL, không viết lại query) | §4.5 | TB | PR1 |
| 5 | `BaseRunDispatcher` gộp Run/Hybrid dispatcher | §2.5 | TB | — |
| 6 | Đưa orchestration ra khỏi `chat_api.post_message` → `ConversationService.start_run()` | §4.6 | TB | PR5 |
| 7 | Test characterization cho HUST parser (thuần thêm test) | §7 | Rất thấp | — |
| 8 | Tách `_extract_tuition_value` | §3 | TB | PR7 |
| 9 | Tách `_parse_card` | §3 | TB | PR7, PR8 |
| 10 | Migrate `llm_extractor` sang inference gateway + gỡ SDK cũ | §2.1 | TB-Cao | — |

---

## PR 1 — Xóa bảng chết `discovered_resources` + đơn giản hóa query evidence

**Title:** `refactor(db): drop dead discovered_resources table & simplify evidence join`

**Goal:** Xóa bảng `discovered_resources` (0 INSERT/SELECT/UPDATE trong toàn repo) và bỏ hai `LEFT JOIN` chết (`extracted_facts`, `raw_documents`) trong query evidence — hai bảng này không bao giờ được populate ở production nên join luôn trả NULL; bỏ chúng là **đơn giản hóa bảo toàn hành vi** (NULL vẫn là NULL). Đây là PR thuần xóa, an toàn nhất.

**Files to modify:**
- `services/conflict/evidence_agent.py:28-43` — bỏ 2 join chết khỏi SQL; `fetched_at` luôn NULL nên giữ cột trả về là `NULL` literal để không đổi shape kết quả.
- `db/setup_db.py:100-114` — bỏ `"discovered_resources"` khỏi danh sách `expected`.
- `tests/services/conflict/test_evidence_agent.py` — cập nhật assertion về SQL nếu test soi nội dung query (kiểm tra trước).

**Files to delete:**
- Không xóa file migration `002_discovered_resources.sql` (migration là lịch sử, idempotent, không xóa). Thay vào đó thêm migration drop mới (xem dưới).

**Migration strategy:**
1. Thêm file mới `db/migrations/014_drop_discovered_resources.sql`:
   ```sql
   -- 014_drop_discovered_resources.sql
   -- discovered_resources never wired to any read/write path (audit §1). Drop it.
   DROP TABLE IF EXISTS discovered_resources CASCADE;
   ```
   Idempotent nhờ `IF EXISTS` — khớp quy ước migration 001–013.
2. Query evidence: hiện tại
   ```python
   sql = """
       SELECT car.source_url, rd.fetched_at
       FROM canonical_admission_records car
       LEFT JOIN extracted_facts ef ON ef.id = car.extracted_fact_id
       LEFT JOIN raw_documents rd ON rd.id = ef.raw_document_id
       WHERE car.source_url = ANY(%s)
         AND car.school_id = %s
         AND car.admission_year = %s
   """
   ```
   Đổi thành (giữ nguyên 2 cột trả về để `package_evidence` không phải đổi):
   ```python
   sql = """
       SELECT car.source_url, NULL::timestamptz AS fetched_at
       FROM canonical_admission_records car
       WHERE car.source_url = ANY(%s)
         AND car.school_id = %s
         AND car.admission_year = %s
   """
   ```
   > Lưu ý: KHÔNG drop `raw_documents`/`extracted_facts` ở PR này — chúng còn FK `canonical_admission_records.extracted_fact_id` và là quyết định riêng (audit để "TB, cần quyết định"). PR này chỉ gỡ join chết + drop bảng 100% chết.

**Test plan:**
- [ ] **Bước 1:** Đọc `tests/services/conflict/test_evidence_agent.py`, xác định test `test_package_evidence_batches_db_lookup_into_one_query` có assert nội dung SQL không. Nếu có assert chuỗi `extracted_facts`/`raw_documents`, sửa assertion cho khớp SQL mới.
- [ ] **Bước 2:** Chạy `pytest tests/services/conflict/test_evidence_agent.py -v` → Expected: PASS (3 test: mock-source skip, graceful-degrade, single-query-batch). `package_evidence` vẫn enrich `fetched_at=None` như cũ.
- [ ] **Bước 3:** (nếu có Docker) `docker compose up -d --wait db && python -m db.setup_db` rồi `pytest -q` → Expected: migration 014 chạy, danh sách bảng không còn `discovered_resources`, toàn bộ xanh.
- [ ] **Bước 4:** `pytest -q` toàn suite → Expected: PASS.
- [ ] **Bước 5:** Commit.
  ```bash
  git add db/migrations/014_drop_discovered_resources.sql services/conflict/evidence_agent.py db/setup_db.py tests/services/conflict/test_evidence_agent.py
  git commit -m "refactor(db): drop dead discovered_resources table & simplify evidence join"
  ```

**Rollback strategy:** `git revert` PR. Bảng `discovered_resources` đã 100% chết nên không có data mất; nếu cần khôi phục schema, chạy lại migration `002`. Vì migration là forward-only, để rollback DB thực tế cần migration down thủ công `CREATE TABLE discovered_resources ...` (copy từ `002`).

---

## PR 2 — Move `agents/models.py` → `domain/models.py` + shim

**Title:** `refactor(arch): move domain models to domain/ package with re-export shim`

**Goal:** Sửa đảo chiều tầng (§4.1): `agents/models.py` chứa domain models thật (`CandidateProgram`, `StudentProfile`, …) nhưng nằm ở tầng orchestration, khiến 13 file `services/` + `state.py` import "lên" `agents`. Di chuyển sang leaf package `domain/`, **để lại shim re-export tại `agents/models.py`** ⇒ bảo toàn 100% public API, mọi import cũ vẫn chạy.

**Files to modify:**
- `state.py:5-12` — đổi import sang `from domain.models import ...` (file tầng cao nhất, nên trỏ thẳng vào nguồn mới).
- (Tùy chọn, KHÔNG bắt buộc trong PR này) các file `services/*` vẫn dùng shim — sẽ migrate dần ở PR sau nếu muốn. PR này chỉ chuyển nguồn + state.py để chứng minh shim hoạt động.

**Files to delete:** Không (file `agents/models.py` được thay bằng shim, không xóa).

**Migration strategy:**
1. Tạo package mới:
   ```bash
   mkdir -p domain
   ```
   Tạo `domain/__init__.py` (rỗng).
2. Di chuyển nội dung (giữ git history):
   ```bash
   git mv agents/models.py domain/models.py
   ```
3. Tạo lại shim `agents/models.py`:
   ```python
   """Re-export shim. Domain models moved to domain.models (audit §4.1).

   Kept so existing `from agents.models import X` keeps working.
   New code should import from domain.models.
   """
   from domain.models import (
       CandidateProgram,
       CutoffAssessment,
       CutoffEntry,
       EligibilityCheck,
       Evidence,
       PolicyDecision,
       RankedRecommendation,
       StudentProfile,
   )

   __all__ = [
       "CandidateProgram",
       "CutoffAssessment",
       "CutoffEntry",
       "EligibilityCheck",
       "Evidence",
       "PolicyDecision",
       "RankedRecommendation",
       "StudentProfile",
   ]
   ```
   > 8 symbol — khớp đúng danh sách class định nghĩa trong `domain/models.py` (StudentProfile, Evidence, CutoffEntry, CutoffAssessment, CandidateProgram, EligibilityCheck, RankedRecommendation, PolicyDecision).
4. Sửa `state.py:5-12`:
   ```python
   from domain.models import (
       CandidateProgram,
       EligibilityCheck,
       Evidence,
       PolicyDecision,
       RankedRecommendation,
       StudentProfile,
   )
   ```

**Test plan:**
- [ ] **Bước 1:** Viết test bảo vệ shim — tạo `tests/domain/test_models_shim.py`:
  ```python
  def test_agents_models_shim_reexports_domain_models():
      from agents.models import CandidateProgram as ShimCP
      from domain.models import CandidateProgram as DomainCP
      assert ShimCP is DomainCP

  def test_all_eight_symbols_importable_via_shim():
      import agents.models as shim
      for name in (
          "CandidateProgram", "CutoffAssessment", "CutoffEntry",
          "EligibilityCheck", "Evidence", "PolicyDecision",
          "RankedRecommendation", "StudentProfile",
      ):
          assert hasattr(shim, name), name
  ```
- [ ] **Bước 2:** `pytest tests/domain/test_models_shim.py -v` TRƯỚC khi tạo shim → Expected: FAIL (`ModuleNotFoundError: domain.models`).
- [ ] **Bước 3:** Thực hiện `git mv` + tạo `domain/__init__.py` + viết shim + sửa `state.py`.
- [ ] **Bước 4:** `pytest tests/domain/test_models_shim.py -v` → Expected: PASS (shim trỏ đúng cùng object).
- [ ] **Bước 5:** `pytest -q` toàn suite → Expected: PASS — 13 file service + 17 file test vẫn import qua shim không đổi.
- [ ] **Bước 6:** Commit.
  ```bash
  git add domain/ agents/models.py state.py tests/domain/test_models_shim.py
  git commit -m "refactor(arch): move domain models to domain/ package with re-export shim"
  ```

**Rollback strategy:** `git revert`. Shim đảm bảo không call-site nào gãy; nếu chỉ muốn lùi `state.py` mà giữ move, đổi import `state.py` về `from agents.models import ...` (vẫn chạy nhờ shim).

---

## PR 3 — Move `GeminiEmbedder` → `services/inference/embedder.py` + shim

**Title:** `refactor(arch): relocate GeminiEmbedder into services/inference with shim`

**Goal:** Gỡ back-edge `ingestion → services` (§4.8). `GeminiEmbedder` đã phụ thuộc `services.inference.providers.key_pool`, nên đặt nó trong `services/inference/` là đúng tầng. **Để lại shim** tại `ingestion/knowledge/embedder.py` ⇒ 4 import hiện tại không gãy.

**Files to modify:**
- `ingestion/knowledge/pipeline.py:16` → `from services.inference.embedder import GeminiEmbedder`.
- `services/knowledge/qa_service.py:7` → `from services.inference.embedder import GeminiEmbedder`.
- `services/profile/major_catalog.py:5` → `from services.inference.embedder import GeminiEmbedder`.
- `services/profile/major_resolver.py:56` (import trong hàm) → đổi path; cân nhắc nâng lên top-level nếu không còn vòng lặp (kiểm tra ở bước test).

**Files to delete:** Không (thay `ingestion/knowledge/embedder.py` bằng shim).

**Migration strategy:**
1. `git mv ingestion/knowledge/embedder.py services/inference/embedder.py`.
   Nội dung giữ nguyên: `l2_normalize()`, class `GeminiEmbedder`, các import top-level đã sẵn (`from ingestion.config.settings import GEMINI_EMBEDDING_MODEL, EMBEDDING_DIM`, `from services.inference.providers.key_pool import GeminiKeyPool, get_key_pool`). Lưu ý import `ingestion.config.settings` từ `services/` là cạnh ổn (settings là leaf cấu hình).
2. Tạo shim `ingestion/knowledge/embedder.py`:
   ```python
   """Re-export shim. GeminiEmbedder moved to services.inference.embedder (audit §4.8)."""
   from services.inference.embedder import GeminiEmbedder, l2_normalize

   __all__ = ["GeminiEmbedder", "l2_normalize"]
   ```
3. Đổi 3 import top-level (pipeline.py, qa_service.py, major_catalog.py) sang path mới.
4. `major_resolver.py:56-57` — import-trong-hàm. Đổi path. Thử nâng lên top-level:
   ```python
   from services.inference.embedder import GeminiEmbedder
   ```
   Nếu `pytest` báo circular import → giữ trong hàm với path mới (vẫn đạt mục tiêu gỡ back-edge ingestion→services vì giờ trỏ services→services).

**Test plan:**
- [ ] **Bước 1:** Di chuyển test theo code: `git mv tests/ingestion/knowledge/test_embedder.py tests/services/inference/test_embedder.py` (tạo `tests/services/inference/__init__.py` nếu cần). Sửa import trong file test:
  ```python
  from services.inference.embedder import GeminiEmbedder, l2_normalize
  ```
- [ ] **Bước 2:** Thêm test shim vào cuối `tests/services/inference/test_embedder.py`:
  ```python
  def test_ingestion_embedder_shim_still_works():
      from ingestion.knowledge.embedder import GeminiEmbedder as Shim
      from services.inference.embedder import GeminiEmbedder as Real
      assert Shim is Real
  ```
- [ ] **Bước 3:** `pytest tests/services/inference/test_embedder.py -v` → Expected: PASS (11 test cũ + 1 test shim).
- [ ] **Bước 4:** `pytest -q` → Expected: PASS — 4 call-site import qua path mới hoặc shim.
- [ ] **Bước 5:** Commit.
  ```bash
  git add services/inference/embedder.py ingestion/knowledge/embedder.py ingestion/knowledge/pipeline.py services/knowledge/qa_service.py services/profile/major_catalog.py services/profile/major_resolver.py tests/services/inference/
  git commit -m "refactor(arch): relocate GeminiEmbedder into services/inference with shim"
  ```

**Rollback strategy:** `git revert`. Shim giữ `ingestion.knowledge.embedder` sống; nếu nâng top-level `major_resolver` gây lỗi runtime mà CI không bắt, đổi lại thành import-trong-hàm (1 dòng).

---

## PR 4 — `ConflictEvidenceRepository` + `CutoffRepository`

**Title:** `refactor(db): wrap conflict/cutoff SQL in repositories with connection_factory`

**Goal:** §4.5 — `services/conflict/evidence_agent.py` và `services/retrieval_service.py` tự gọi `get_cursor`/`get_connection` từ `ingestion.storage.db_connection`, bỏ qua pattern repository. Gói SQL hiện có vào 2 repository nhận `connection_factory` (dùng `services/db.cursor`), **không viết lại query**. Public function `package_evidence` và các hàm retrieval giữ nguyên chữ ký.

**Files to modify:**
- `services/conflict/evidence_agent.py` — `package_evidence` ủy quyền truy vấn DB cho `ConflictEvidenceRepository`.
- `services/retrieval_service.py` — `fetch_cutoff_history` ủy quyền cho `CutoffRepository`; giữ chữ ký hàm public.

**Files to create:**
- `services/conflict/repository.py` — `ConflictEvidenceRepository`.
- `services/retrieval/repository.py` — `CutoffRepository` (tạo package `services/retrieval/` với `__init__.py` nếu chưa có; nếu muốn tránh package mới, đặt `services/cutoff/repository.py` cạnh `services/cutoff/assessment.py`). Plan dùng `services/cutoff/repository.py` (đã có package `services/cutoff/`).

**Files to delete:** Không.

**Migration strategy:**
1. Tạo `services/conflict/repository.py`, bê **nguyên văn** SQL từ `evidence_agent.py` (đã đơn giản hóa ở PR1):
   ```python
   from ingestion.storage.db_connection import get_connection
   from services.db import cursor


   class ConflictEvidenceRepository:
       """Read source_url + fetched_at for canonical records (audit §4.5)."""

       def __init__(self, connection_factory=get_connection):
           self.connection_factory = connection_factory

       def fetch_fetched_at_by_source(self, source_urls, school_id, admission_year):
           sql = """
               SELECT car.source_url, NULL::timestamptz AS fetched_at
               FROM canonical_admission_records car
               WHERE car.source_url = ANY(%s)
                 AND car.school_id = %s
                 AND car.admission_year = %s
           """
           with cursor(self.connection_factory, commit=False) as cur:
               cur.execute(sql, (list(source_urls), school_id, admission_year))
               return {row[0]: row[1] for row in cur.fetchall()}
   ```
   > `services/db.cursor(connection_factory, commit=...)` là helper dùng chung đã tồn tại (`services/db/__init__.py`). `get_connection` (raw factory) đã được `services/profile/major_catalog_repository.py` dùng theo đúng pattern này.
2. Trong `evidence_agent.py`, thay block `with get_cursor(...) as cur: cur.execute(sql, ...)` bằng:
   ```python
   from services.conflict.repository import ConflictEvidenceRepository
   # ... trong package_evidence, chỗ enrich:
   repo = _evidence_repo or ConflictEvidenceRepository()
   fetched_map = repo.fetch_fetched_at_by_source(
       source_urls, record.school_id, record.admission_year
   )
   ```
   Cho phép inject để test: thêm tham số tùy chọn `_evidence_repo=None` vào `package_evidence` **với default None** ⇒ giữ chữ ký công khai tương thích ngược (caller cũ không truyền vẫn chạy).
3. Tương tự tạo `services/cutoff/repository.py` với `CutoffRepository.fetch_cutoff_history(pairs)` bê nguyên SQL từ `retrieval_service.fetch_cutoff_history` (lines 57-99), và `fetch_cutoff_history` cũ gọi repo.

**Test plan:**
- [ ] **Bước 1:** Viết `tests/services/conflict/test_conflict_repository.py` với fake connection_factory:
  ```python
  from services.conflict.repository import ConflictEvidenceRepository

  class _FakeCursor:
      def __init__(self, rows): self._rows = rows; self.executed = None
      def execute(self, sql, params): self.executed = (sql, params)
      def fetchall(self): return self._rows
      def __enter__(self): return self
      def __exit__(self, *a): return False

  class _FakeConn:
      def __init__(self, rows): self._cur = _FakeCursor(rows)
      def cursor(self): return self._cur
      def commit(self): pass
      def rollback(self): pass
      def close(self): pass

  def test_fetch_fetched_at_maps_rows_by_source_url():
      conn = _FakeConn([("https://a", None), ("https://b", None)])
      repo = ConflictEvidenceRepository(connection_factory=lambda: conn)
      result = repo.fetch_fetched_at_by_source(["https://a", "https://b"], "hust", 2024)
      assert result == {"https://a": None, "https://b": None}
  ```
- [ ] **Bước 2:** `pytest tests/services/conflict/test_conflict_repository.py -v` TRƯỚC khi tạo repo → Expected: FAIL (`ModuleNotFoundError`).
- [ ] **Bước 3:** Tạo `services/conflict/repository.py` + `services/cutoff/repository.py`, sửa 2 call-site ủy quyền.
- [ ] **Bước 4:** `pytest tests/services/conflict/test_conflict_repository.py tests/services/conflict/test_evidence_agent.py -v` → Expected: PASS (repo unit + evidence agent vẫn xanh).
- [ ] **Bước 5:** Viết test tương tự `tests/services/cutoff/test_cutoff_repository.py` cho `CutoffRepository` (cùng khuôn fake), chạy → PASS.
- [ ] **Bước 6:** `pytest -q` toàn suite (kèm `test_retrieval_service.py`) → Expected: PASS.
- [ ] **Bước 7:** Commit.
  ```bash
  git add services/conflict/repository.py services/cutoff/repository.py services/conflict/evidence_agent.py services/retrieval_service.py tests/services/conflict/test_conflict_repository.py tests/services/cutoff/test_cutoff_repository.py
  git commit -m "refactor(db): wrap conflict/cutoff SQL in repositories with connection_factory"
  ```

**Rollback strategy:** `git revert`. Vì SQL không đổi, hành vi DB giữ nguyên; nếu repo gây lỗi inject, các call-site có default `None` nên có thể tạm hoàn nguyên 1 call-site về `get_cursor` cũ mà không đụng cái còn lại.

---

## PR 5 — `BaseRunDispatcher` gộp Run/Hybrid dispatcher

**Title:** `refactor(chat): extract BaseRunDispatcher to dedupe Run/Hybrid dispatchers`

**Goal:** §2.5 — `RunDispatcher` và `HybridDispatcher` có `__init__`, `submit` fire-and-forget, `_execute`, `_mark_failed` cấu trúc gần như giống hệt (chỉ khác callable runner vs orchestrator và text lỗi tiếng Việt). Trích base class chung, gỡ copy-paste, sửa luôn lệch dấu trong message. **Giữ nguyên** `get_run_dispatcher()`/`get_hybrid_dispatcher()` và chữ ký `submit()` của cả hai.

**Files to modify:**
- `services/chat/run_dispatcher.py` — `RunDispatcher` kế thừa `BaseRunDispatcher`.
- `services/chat/hybrid_dispatcher.py` — `HybridDispatcher` kế thừa `BaseRunDispatcher`.

**Files to create:**
- `services/chat/base_dispatcher.py` — `BaseRunDispatcher` chứa logic chung (`__init__` executor, `_mark_failed`, khung `_execute`).

**Files to delete:** Không.

**Migration strategy:**
1. Tạo `services/chat/base_dispatcher.py`:
   ```python
   from concurrent.futures import ThreadPoolExecutor

   from services.chat.repository import ChatSessionRepository


   class BaseRunDispatcher:
       """Shared fire-and-forget run dispatching (audit §2.5).

       Subclass overrides _run(record) to perform the actual work and return
       (final_answer, result_json). Everything else (threadpool, status
       bookkeeping, failure recovery) is shared.
       """

       def __init__(self, repository=None, executor=None):
           self.repository = repository or ChatSessionRepository()
           self.executor = executor or ThreadPoolExecutor(max_workers=2)

       def _mark_failed(self, session_token, run_id, error):
           # Single source of truth for the failure message (fixes drift).
           self.repository.append_message(
               session_token,
               role="assistant",
               content="Xin lỗi, đã có lỗi khi xử lý yêu cầu. Vui lòng thử lại.",
           )
           self.repository.update_session_status(session_token, "error")
   ```
   > Lấy đúng text/logic từ `_mark_failed` hiện tại; nếu hai bản đang khác chữ, chọn bản đúng dấu tiếng Việt làm chuẩn (đây chính là "sửa message lệch dấu" mà audit nêu).
2. `RunDispatcher` rút gọn:
   ```python
   from services.chat.base_dispatcher import BaseRunDispatcher
   from services.chat.advisory_runner import run_advisory_for_session

   class RunDispatcher(BaseRunDispatcher):
       def __init__(self, repository=None, runner=None, executor=None):
           super().__init__(repository=repository, executor=executor)
           self.runner = runner or run_advisory_for_session

       def submit(self, *, session_token, run_id, latest_user_message,
                  profile_state, correction_note=None, closing_seed=0):
           self.executor.submit(
               self._execute,
               session_token, run_id, latest_user_message,
               profile_state, correction_note, closing_seed,
           )

       def _execute(self, session_token, run_id, latest_user_message,
                    profile_state, correction_note, closing_seed):
           # GIỮ NGUYÊN thân _execute hiện tại; chỉ gọi self._mark_failed (kế thừa).
           ...
   ```
   `HybridDispatcher` tương tự, giữ `submit(session_token, run_id, content, profile_state, intent)` và thân `_execute` cũ, bỏ bản `_mark_failed` riêng (dùng của base).

**Test plan:**
- [ ] **Bước 1:** Chạy `pytest tests/services/chat/test_run_dispatcher.py tests/services/chat/test_hybrid_dispatcher.py -v` (baseline hiện tại) → Expected: PASS — ghi nhận hành vi gốc.
- [ ] **Bước 2:** Thêm test khẳng định cùng `_mark_failed` `tests/services/chat/test_base_dispatcher.py`:
  ```python
  from services.chat.run_dispatcher import RunDispatcher
  from services.chat.hybrid_dispatcher import HybridDispatcher
  from services.chat.base_dispatcher import BaseRunDispatcher

  def test_both_dispatchers_share_base_mark_failed():
      assert RunDispatcher._mark_failed is BaseRunDispatcher._mark_failed
      assert HybridDispatcher._mark_failed is BaseRunDispatcher._mark_failed
  ```
- [ ] **Bước 3:** `pytest tests/services/chat/test_base_dispatcher.py -v` TRƯỚC khi refactor → Expected: FAIL (`AttributeError`/`ModuleNotFoundError`).
- [ ] **Bước 4:** Tạo base + refactor 2 dispatcher.
- [ ] **Bước 5:** `pytest tests/services/chat/test_base_dispatcher.py tests/services/chat/test_run_dispatcher.py tests/services/chat/test_hybrid_dispatcher.py -v` → Expected: PASS (cả 3, dùng InlineExecutor/FakeRepository sẵn có).
- [ ] **Bước 6:** `pytest -q` → Expected: PASS.
- [ ] **Bước 7:** Commit.
  ```bash
  git add services/chat/base_dispatcher.py services/chat/run_dispatcher.py services/chat/hybrid_dispatcher.py tests/services/chat/test_base_dispatcher.py
  git commit -m "refactor(chat): extract BaseRunDispatcher to dedupe Run/Hybrid dispatchers"
  ```

**Rollback strategy:** `git revert`. `submit()` của cả hai giữ chữ ký nên route/`start_run` không bị ảnh hưởng; nếu base gây lỗi, có thể inline lại `_mark_failed` vào từng dispatcher (copy từ base) mà không đổi `submit`.

---

## PR 6 — Orchestration ra khỏi `chat_api.post_message` → `ConversationService.start_run()`

**Title:** `refactor(web): move run orchestration into ConversationService.start_run`

**Goal:** §4.6 — `post_message` đang tự `repo.create_run`, tính `closing_seed`, chọn dispatcher (logic tầng service nằm trong transport). Dời sang `ConversationService.start_run(...)`; route chỉ validate + delegate. **Giữ nguyên** response payload và behavior.

**Files to modify:**
- `services/chat/conversation_service.py` — thêm method `start_run(session_token, content, result)`.
- `web/routes/chat_api.py:48-74` — `post_message` rút còn validate + gọi `service.handle_user_message` + `service.start_run`.

**Files to delete:** Không.

**Migration strategy:**
1. Thêm vào `ConversationService` (constructor đã có `repository`; cần truy cập dispatcher — inject để test):
   ```python
   def __init__(self, repository=None, extract_profile=None, intent_router=None,
                knowledge_qa=None, run_dispatcher=None, hybrid_dispatcher=None):
       self.repository = repository or ChatSessionRepository()
       self.extract_profile = extract_profile or self._extract_profile
       self.intent_router = intent_router or IntentRouter()
       self.knowledge_qa = knowledge_qa or KnowledgeQAService()
       self._run_dispatcher = run_dispatcher
       self._hybrid_dispatcher = hybrid_dispatcher

   def start_run(self, session_token, content, result):
       """Create the run row and dispatch it. Mirrors old post_message logic."""
       if not result.should_start_run:
           return
       run_id = self.repository.create_run(session_token, result.profile_state)
       if result.run_kind == "hybrid":
           from services.chat.hybrid_dispatcher import get_hybrid_dispatcher
           from services.chat.intent_router import IntentResult
           intent = IntentResult.model_validate(
               result.hybrid_intent or {"route": "HYBRID"}
           )
           dispatcher = self._hybrid_dispatcher or get_hybrid_dispatcher()
           dispatcher.submit(
               session_token=session_token, run_id=run_id, content=content,
               profile_state=result.profile_state, intent=intent,
           )
       else:
           from services.chat.run_dispatcher import get_run_dispatcher
           closing_seed = max(0, self.repository.count_runs(session_token) - 1)
           dispatcher = self._run_dispatcher or get_run_dispatcher()
           dispatcher.submit(
               session_token=session_token, run_id=run_id,
               latest_user_message=content, profile_state=result.profile_state,
               correction_note=result.correction_note, closing_seed=closing_seed,
           )
   ```
   > Logic bê **nguyên** từ `post_message` (create_run → closing_seed → chọn dispatcher), chỉ đổi nguồn dispatcher để inject được.
2. `post_message` rút gọn:
   ```python
   @router.post("/{session_token}/messages")
   def post_message(session_token: str, payload: ChatMessageCreate):
       service = get_conversation_service()
       result = service.handle_user_message(session_token, payload.content)
       service.start_run(session_token, payload.content, result)
       return result.model_dump()
   ```

**Test plan:**
- [ ] **Bước 1:** Viết `tests/services/chat/test_start_run.py` (dùng FakeRepository có `create_run`/`count_runs` + Fake dispatcher capture submit):
  ```python
  def test_start_run_dispatches_advisory_with_closing_seed():
      # result.should_start_run=True, run_kind="advisory"
      # assert run_dispatcher.submit nhận closing_seed = count_runs-1, run_id từ create_run
      ...
  def test_start_run_dispatches_hybrid_with_intent():
      # run_kind="hybrid" → hybrid_dispatcher.submit nhận intent đã validate
      ...
  def test_start_run_noop_when_should_start_run_false():
      # create_run KHÔNG được gọi
      ...
  ```
  (Mô phỏng theo FakeRepository/FakeDispatcher trong `tests/web/test_chat_session_api.py` lines 43/193.)
- [ ] **Bước 2:** `pytest tests/services/chat/test_start_run.py -v` TRƯỚC khi thêm method → Expected: FAIL (`AttributeError: start_run`).
- [ ] **Bước 3:** Thêm `start_run` + rút gọn `post_message`.
- [ ] **Bước 4:** `pytest tests/services/chat/test_start_run.py -v` → Expected: PASS.
- [ ] **Bước 5:** `pytest tests/web/test_chat_session_api.py -v` → Expected: PASS — các test web (`test_post_message_returns_ready_payload`, `test_post_message_dispatches_hybrid_run`, `test_post_message_rejects_oversized_content`) vẫn xanh vì payload không đổi.
- [ ] **Bước 6:** `pytest -q` → Expected: PASS.
- [ ] **Bước 7:** Commit.
  ```bash
  git add services/chat/conversation_service.py web/routes/chat_api.py tests/services/chat/test_start_run.py
  git commit -m "refactor(web): move run orchestration into ConversationService.start_run"
  ```

**Rollback strategy:** `git revert`. Payload/route path không đổi; nếu `start_run` lỗi, có thể tạm khôi phục thân cũ của `post_message` (đã có trong git history) trong khi giữ method `start_run` mới chưa dùng.

---

## PR 7 — Test characterization cho HUST parser (thuần thêm test)

**Title:** `test(ingestion): characterization tests for HUST _parse_card & tuition extraction`

**Goal:** §7 — `hust_program_parser.py` là module lớn nhất không có test cho `_parse_card`/`_extract_tuition_value`. Trước khi tách (PR8/PR9), **khóa hành vi hiện tại** bằng test characterization dựa trên fixture có sẵn. PR này KHÔNG đổi production code ⇒ rủi ro gần như 0.

**Files to modify:** Không (chỉ thêm test).

**Files to create:**
- `tests/ingestion/test_hust_parse_card.py`
- `tests/ingestion/test_hust_tuition.py`
- (nếu cần) thêm fixture HTML chi tiết tuition vào `ingestion/parsers/_fixtures/`.

**Files to delete:** Không.

**Migration strategy:** Dùng fixture sẵn có `ingestion/parsers/_fixtures/hust_program_card.html`. Test gọi `HustProgramParser(...).parse(content, url, ...)` với `_fetch_detail_pages=False` (hoặc inject http_fetch fake) để tránh network I/O thật, rồi assert các field của `ExtractedAdmissionFact` đầu ra. Với tuition, gọi trực tiếp helper module-level `_extract_tuition_value(soup, lines, target_program_code)`.

**Test plan:**
- [ ] **Bước 1:** `tests/ingestion/test_hust_parse_card.py` — khóa happy-path từ fixture:
  ```python
  from pathlib import Path
  from ingestion.parsers.hust_program_parser import HustProgramParser

  FIXTURE = Path("ingestion/parsers/_fixtures/hust_program_card.html").read_bytes()

  def _parse():
      parser = HustProgramParser(fetch_detail_pages=False)  # tắt network
      return parser.parse(FIXTURE, "https://ts.hust.edu.vn/", school_id="hust")

  def test_parse_card_extracts_code_and_name():
      facts = _parse()
      assert len(facts) == 1
      f = facts[0]
      assert f.program_code == "BF-E12"
      assert "Kỹ thuật thực phẩm" in f.program_name

  def test_parse_card_extracts_combos_deduped():
      f = _parse()[0]
      assert f.subject_combinations_raw == ["K00", "A00", "B00", "D07", "K01"]

  def test_parse_card_extracts_language_and_faculty_in_conditions():
      import json
      f = _parse()[0]
      cond = json.loads(f.additional_conditions_raw)
      assert cond["language"] == "Tiếng Anh"
      assert "Hóa và Khoa học sự sống" in cond["faculty"]
  ```
  > Nếu kết quả thực tế khác (ví dụ thứ tự combo), **sửa assertion cho khớp output hiện tại** — characterization khóa hành vi *đang có*, không phải hành vi *mong muốn*. Tên tham số tắt-network (`fetch_detail_pages` vs `_fetch_detail_pages`) kiểm tra theo constructor thật trước khi viết.
- [ ] **Bước 2:** `tests/ingestion/test_hust_tuition.py` — khóa 4 fallback của `_extract_tuition_value`:
  ```python
  from bs4 import BeautifulSoup
  from ingestion.parsers.hust_program_parser import _extract_tuition_value

  def test_tuition_from_strong_in_tab1_li():
      html = '<div id="tab_1"><div><div class="wrap_view"><ul>' \
             '<li>Học phí: <strong>55 - 65</strong></li></ul></div></div></div>'
      soup = BeautifulSoup(html, "html.parser")
      assert _extract_tuition_value(soup, []) == "55-65"

  def test_tuition_fallback_to_lines_range():
      soup = BeautifulSoup("<html></html>", "html.parser")
      lines = ["Học phí dự kiến: 24 - 30 triệu/năm"]
      assert _extract_tuition_value(soup, lines) == "24-30"

  def test_tuition_returns_sentinel_when_absent():
      soup = BeautifulSoup("<html></html>", "html.parser")
      assert _extract_tuition_value(soup, []) == "Không thông tin"
  ```
  > Chạy thật để lấy giá trị trả về chính xác rồi chốt assertion (ví dụ range có thể trả `"24-30"` hay `"24 - 30 triệu/năm"` tùy nhánh — khóa đúng cái thực tế).
- [ ] **Bước 3:** `pytest tests/ingestion/test_hust_parse_card.py tests/ingestion/test_hust_tuition.py -v` → Expected: PASS sau khi chốt assertion khớp output hiện tại.
- [ ] **Bước 4:** `pytest -q` → Expected: PASS.
- [ ] **Bước 5:** Commit.
  ```bash
  git add tests/ingestion/test_hust_parse_card.py tests/ingestion/test_hust_tuition.py
  git commit -m "test(ingestion): characterization tests for HUST _parse_card & tuition extraction"
  ```

**Rollback strategy:** `git revert` (chỉ là test, không ảnh hưởng runtime). An toàn tuyệt đối.

---

## PR 8 — Tách `_extract_tuition_value`

**Title:** `refactor(ingestion): split _extract_tuition_value into per-fallback helpers`

**Goal:** §3 — `_extract_tuition_value` (lines 121-194, 4 chiến lược fallback + regex range lặp 2 nơi) khó đọc. Trích regex chung thành hằng `_TUITION_RANGE_RE` và tách 4 fallback thành helper nhỏ. Hành vi giữ nguyên (PR7 bảo vệ).

**Files to modify:**
- `ingestion/parsers/hust_program_parser.py` — thêm hằng `_TUITION_RANGE_RE`, tách `_extract_tuition_value` thành các helper module-level: `_tuition_from_tab1`, `_tuition_from_all_lis`, `_tuition_from_lines`, `_tuition_from_segment`; `_extract_tuition_value` gọi lần lượt.

**Files to delete:** Không.

**Migration strategy:**
1. Thêm hằng cạnh các regex khác:
   ```python
   _TUITION_RANGE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*[-–]\s*(\d+(?:[.,]\d+)?)")
   ```
   Thay 2 chỗ inline (`_extract_tuition_from_li` ~line 98, fallback 3 ~line 171) dùng `_TUITION_RANGE_RE.search(...)`.
2. Tách thân `_extract_tuition_value` (giữ thứ tự fallback 1→4 nguyên vẹn):
   ```python
   def _extract_tuition_value(soup, lines, target_program_code=None):
       return (
           _tuition_from_tab1(soup, target_program_code)
           or _tuition_from_all_lis(soup)
           or _tuition_from_lines(lines)
           or _tuition_from_segment(lines)
           or "Không thông tin"
       )
   ```
   Mỗi helper trả `str | None`; bê nguyên logic từng nhánh hiện tại, đổi `return "..."` giữa chừng thành `return value` / cuối hàm `return None`.

**Test plan:**
- [ ] **Bước 1:** Chạy lại PR7 tuition tests làm baseline: `pytest tests/ingestion/test_hust_tuition.py -v` → Expected: PASS.
- [ ] **Bước 2:** Thêm test cho từng helper mới trong cùng file:
  ```python
  from ingestion.parsers.hust_program_parser import _tuition_from_lines, _tuition_from_segment

  def test_tuition_from_lines_handles_colon_value():
      assert _tuition_from_lines(["Học phí: 30 triệu"]) == "30 triệu"

  def test_tuition_from_segment_returns_none_when_no_keyword():
      assert _tuition_from_segment(["Không liên quan"]) is None
  ```
  > Chốt giá trị thực tế sau khi chạy (giữ đồng nhất với behavior cũ).
- [ ] **Bước 3:** `pytest tests/ingestion/test_hust_tuition.py -v` SAU khi tách → Expected: PASS (cả test cũ PR7 lẫn test helper mới).
- [ ] **Bước 4:** `pytest -q` → Expected: PASS.
- [ ] **Bước 5:** Commit.
  ```bash
  git add ingestion/parsers/hust_program_parser.py tests/ingestion/test_hust_tuition.py
  git commit -m "refactor(ingestion): split _extract_tuition_value into per-fallback helpers"
  ```

**Rollback strategy:** `git revert`. PR7 đảm bảo bất kỳ lệch hành vi nào cũng làm test đỏ trước khi commit; nếu phát hiện sau, revert đưa về hàm gốc nguyên khối.

---

## PR 9 — Tách `_parse_card`

**Title:** `refactor(ingestion): decompose HustProgramParser._parse_card into focused helpers`

**Goal:** §3 — `_parse_card` (~lines 418-587, ~120 dòng) trộn parse + network I/O + dựng record. Tách theo ranh giới comment sẵn có thành các method `self._extract_program_header / _extract_subject_combos / _extract_admission_methods / _extract_quota / _extract_language / _extract_faculty / _fetch_and_merge_detail / _build_conditions`. Hành vi giữ nguyên (PR7 bảo vệ).

**Files to modify:**
- `ingestion/parsers/hust_program_parser.py` — `_parse_card` chỉ còn điều phối; logic chuyển vào các helper là instance method (`self`) vì cần context parser (cache, `_fetch_detail_pages`, base url).

**Files to delete:** Không.

**Migration strategy:** Tách thuần cơ học từng block (đã xác định ranh giới):
- header (430-458) → `_extract_program_header(card, text) -> tuple[str|None, str|None]` trả `(program_name, program_code)`.
- combos (467-480) → `_extract_subject_combos(card, text) -> list[str]`.
- methods (483-489) → `_extract_admission_methods(card) -> list[str]`.
- quota (492-498) → `_extract_quota(card) -> str`.
- language (501-505) → `_extract_language(card) -> str|None`.
- faculty (508-515) → `_extract_faculty(text) -> str|None`.
- detail fetch + merge (518-537) → `_fetch_and_merge_detail(card, source_url, program_code, method_lines) -> dict` (giữ nguyên `self._fetch_detail_payload`, network I/O nằm gọn ở đây).
- conditions (540-558) → `_build_conditions(language, faculty, detail_url, detail_payload) -> dict`.

`_parse_card` mới gọi lần lượt rồi `return ExtractedAdmissionFact(...)` y như cũ. **Không đổi** thứ tự, không đổi giá trị `confidence_score=0.85`, `extraction_method="hust_program_parser"`.

**Test plan:**
- [ ] **Bước 1:** Baseline: `pytest tests/ingestion/test_hust_parse_card.py -v` → Expected: PASS (từ PR7).
- [ ] **Bước 2:** Thêm test cho 2 helper thuần (không cần network) để tăng độ phủ:
  ```python
  from ingestion.parsers.hust_program_parser import HustProgramParser
  from bs4 import BeautifulSoup

  def test_extract_program_header_from_h3():
      card = BeautifulSoup(
          '<div><h3>01 - ( BF-E12 ) Kỹ thuật thực phẩm</h3></div>', "html.parser"
      ).div
      parser = HustProgramParser(fetch_detail_pages=False)
      name, code = parser._extract_program_header(card, card.get_text("\n", strip=True))
      assert code == "BF-E12"
      assert "Kỹ thuật thực phẩm" in name
  ```
  > Kiểm tra tên constructor flag thật trước khi viết.
- [ ] **Bước 3:** Tách `_parse_card` thành các helper.
- [ ] **Bước 4:** `pytest tests/ingestion/test_hust_parse_card.py -v` → Expected: PASS (3 test characterization PR7 + test helper mới) — chứng minh tách không đổi output.
- [ ] **Bước 5:** `pytest -q` → Expected: PASS.
- [ ] **Bước 6:** Commit.
  ```bash
  git add ingestion/parsers/hust_program_parser.py tests/ingestion/test_hust_parse_card.py
  git commit -m "refactor(ingestion): decompose HustProgramParser._parse_card into focused helpers"
  ```

**Rollback strategy:** `git revert`. Đây là PR rủi ro nhất trong nhóm parser, nhưng PR7 (characterization) làm lưới an toàn: bất kỳ thay đổi output nào ⇒ test đỏ ngay tại bước 4, không commit. Revert đưa `_parse_card` về một khối.

---

## PR 10 — Migrate `llm_extractor` sang inference gateway + gỡ SDK cũ

**Title:** `refactor(ingestion): route llm_extractor through inference gateway, drop legacy SDK`

**Goal:** §2.1 (giá trị cao nhất nhóm trùng lặp) — `llm_extractor.py` đang dùng SDK cũ `google.generativeai` trực tiếp, tự strip ```` ``` ````-fence + `json.loads`, **không xoay key / không telemetry / không fallback**, nuốt lỗi trả `[]`. Định tuyến qua `build_default_gateway().run(...)` để có key-rotation/telemetry/fallback theo đúng quy ước CLAUDE.md, **giữ nguyên** chữ ký công khai `llm_extract(...)`. Đây là PR rủi ro nhất vì đổi đường gọi LLM trên code path chưa có test — nên có FakeGateway test bọc trước.

**Files to modify:**
- `services/inference/factory.py` (registry) — thêm policy cho agent mới `fact_extractor` (output_mode JSON, allow_fallback, fallback `gemini-2.5-flash-lite`).
- `ingestion/extractors/llm_extractor.py` — thay thân `llm_extract` bằng gọi gateway; **giữ chữ ký** `llm_extract(parsed, source_ref, school_name="Unknown") -> List[ExtractedAdmissionFact]`.

**Files to delete:** Không xóa file `llm_extractor.py` (giữ public API `llm_extract`). Chỉ xóa **đường import SDK cũ** bên trong nó (`import google.generativeai as genai` + nhánh dynamic import).

**Migration strategy:**
1. Thêm vào registry trong `services/inference/factory.py` (theo khuôn các agent khác):
   ```python
   "fact_extractor": InferencePolicy(
       agent_name="fact_extractor",
       primary_model="gemini-2.5-flash",
       fallback_model="gemini-2.5-flash-lite",
       allow_fallback=True,
       output_mode="json",
       max_retries=1,
   ),
   ```
2. Viết lại thân `llm_extract` (giữ chữ ký + giữ build prompt hiện có):
   ```python
   import json
   import logging
   from typing import List

   from services.inference.factory import build_default_gateway
   from services.inference.models import InferenceError, InferenceRequest

   logger = logging.getLogger(__name__)

   def llm_extract(parsed, source_ref, school_name="Unknown", *, gateway=None):
       prompt = _build_prompt(parsed, school_name)   # giữ nguyên hàm dựng prompt cũ
       gw = gateway or build_default_gateway()
       try:
           result = gw.run(
               InferenceRequest(
                   agent_name="fact_extractor",
                   task_type="admission_fact_extraction",
                   system_prompt=_SYSTEM_PROMPT,    # tách phần system khỏi prompt cũ
                   user_prompt=prompt,
                   output_mode="json",
                   temperature=0.0,
               )
           )
       except InferenceError as exc:
           logger.warning("llm_extract degraded (gateway failure): %s", exc)
           return []   # giữ hành vi degrade graceful như cũ
       raw = result.parsed_data
       if raw is None:
           # gateway đã retry STRUCTURE_FAILURE; vẫn rỗng ⇒ degrade
           logger.warning("llm_extract got no parseable JSON")
           return []
       return _to_facts(raw, source_ref, school_name)   # tách phần map JSON→fact cũ
   ```
   > Provider mới (`google.genai`) đã set `response_mime_type="application/json"` khi `json_mode`, nên **bỏ hẳn** đoạn strip ```` ``` ````-fence + `json.loads` thủ công. `gateway` injectable để test bằng FakeGateway.
3. Xóa trong `llm_extractor.py`: `import google.generativeai as genai`, nhánh `genai.GenerativeModel(...)`/`model.generate_content(...)`, đoạn strip fence. `admission_extractor.py:46-48` **không đổi** (vẫn `from ingestion.extractors.llm_extractor import llm_extract`).
4. (Không thuộc PR này nhưng ghi chú) `google-generativeai` không nằm trong `requirements.txt` (chỉ dynamic import) ⇒ không cần sửa requirements; sau PR này repo sạch SDK cũ.

**Test plan:**
- [ ] **Bước 1:** Viết `tests/ingestion/extractors/test_llm_extractor.py` với FakeGateway (theo khuôn `tests/services/test_policy_inference_service.py`):
  ```python
  from ingestion.extractors.llm_extractor import llm_extract
  from services.inference.models import InferenceError, InferenceResult
  from ingestion.models.pipeline_models import ParsedContent, SourceReference  # path thật cần xác nhận

  class _FakeGateway:
      def __init__(self, result=None, exc=None):
          self._result, self._exc = result, exc
          self.requests = []
      def run(self, request):
          self.requests.append(request)
          if self._exc: raise self._exc
          return self._result

  def _result(parsed):
      return InferenceResult(agent_name="fact_extractor", model="fake",
                             provider="fake", content="{}", parsed_data=parsed)

  def test_llm_extract_maps_gateway_json_to_facts():
      parsed_json = {"facts": [{"program_name": "CNTT", "program_code": "IT1",
                    "admission_method_raw": "THPT", "quota_raw": "100"}]}
      gw = _FakeGateway(result=_result(parsed_json))
      facts = llm_extract(_dummy_parsed(), _dummy_source_ref(), "HUST", gateway=gw)
      assert facts and facts[0].program_code == "IT1"
      assert gw.requests[0].agent_name == "fact_extractor"

  def test_llm_extract_returns_empty_on_inference_error():
      gw = _FakeGateway(exc=InferenceError("boom"))
      assert llm_extract(_dummy_parsed(), _dummy_source_ref(), "HUST", gateway=gw) == []

  def test_llm_extract_returns_empty_when_no_parsed_data():
      gw = _FakeGateway(result=_result(None))
      assert llm_extract(_dummy_parsed(), _dummy_source_ref(), "HUST", gateway=gw) == []
  ```
  > Xác nhận shape JSON thật mà prompt yêu cầu (`{"facts": [...]}` hay list trần) bằng cách đọc prompt hiện có; chốt `_to_facts` cho khớp.
- [ ] **Bước 2:** `pytest tests/ingestion/extractors/test_llm_extractor.py -v` TRƯỚC khi sửa → Expected: FAIL (`llm_extract` chưa nhận `gateway=`, chưa dùng gateway).
- [ ] **Bước 3:** Thêm policy `fact_extractor`, viết lại `llm_extract`, gỡ SDK cũ.
- [ ] **Bước 4:** `pytest tests/ingestion/extractors/test_llm_extractor.py -v` → Expected: PASS (3 test: map JSON, degrade on error, degrade on no-data).
- [ ] **Bước 5:** `git grep -n "google.generativeai"` → Expected: **0 kết quả** (SDK cũ đã sạch).
- [ ] **Bước 6:** `pytest -q` → Expected: PASS (kể cả test `admission_extractor` nếu có).
- [ ] **Bước 7:** Commit.
  ```bash
  git add services/inference/factory.py ingestion/extractors/llm_extractor.py tests/ingestion/extractors/test_llm_extractor.py
  git commit -m "refactor(ingestion): route llm_extractor through inference gateway, drop legacy SDK"
  ```

**Rollback strategy:** `git revert`. Rủi ro chính: đổi semantics lỗi (trước nuốt mọi `Exception` → `[]`; nay degrade trên `InferenceError`/no-data → `[]`, nhưng lỗi lập trình khác sẽ nổi lên thay vì bị nuốt). Nếu ingestion production gặp lỗi mới lộ ra, revert đưa lại bản nuốt-lỗi cũ; FakeGateway tests giữ nguyên để tái migrate. Vì `llm_extract` giữ chữ ký, `admission_extractor.py` không cần đụng khi revert.

---

## Self-Review (đối chiếu spec §9 bảng P2)

| Mục P2 trong audit | PR phủ |
|--------------------|--------|
| Migrate `llm_extractor` sang gateway (§2.1) | PR 10 ✅ |
| Move `agents/models.py`→`domain/models.py` + shim (§4.1) | PR 2 ✅ |
| Move `GeminiEmbedder`→`services/inference/` (§4.8) | PR 3 ✅ |
| Tách `_parse_card`/`_extract_tuition_value` (§3) + test §7 trước | PR 7 (test) → PR 8 + PR 9 ✅ |
| Orchestration ra khỏi `chat_api.post_message`→`start_run()` (§4.6) | PR 6 ✅ |
| Repository cho conflict/cutoff SQL (§4.5) | PR 4 ✅ |
| `BaseRunDispatcher` gộp Run/Hybrid (§2.5) | PR 5 ✅ |
| Quyết định `discovered_resources` + đường `raw_documents/extracted_facts` (§1) | PR 1 ✅ (drop `discovered_resources` + gỡ join chết; **quyết định giữ** `raw_documents`/`extracted_facts` vì còn FK — không drop, chỉ gỡ join) |

**Lưu ý các mục audit đã hoàn thành ngoài P2 (không cần PR):** `services/db/` cursor helper (P1 §2.3/2.6/2.7), `services/formatting.py` (§4.4), `Field(max_length=4000)` cho `ChatMessageCreate` (C2), và `parse_hust_programs`/`run_ingestion` legacy đã bị xóa (P0 §1). Đã kiểm chứng qua đọc code thực tế ngày 2026-06-16.

**Quyết định cần xác nhận của bạn:** PR1 chọn **giữ** `raw_documents`/`extracted_facts` (chỉ gỡ join chết, không drop) vì còn ràng buộc FK `canonical_admission_records.extracted_fact_id`. Nếu bạn muốn **bật lại** đường ghi facts (populate 2 bảng) thay vì coi là zombie, đó là một hướng khác (thuộc tinh thần "nối lại" của §1) và nên là PR riêng — báo mình nếu muốn bổ sung.
