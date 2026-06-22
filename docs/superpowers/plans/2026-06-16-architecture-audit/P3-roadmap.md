# Lộ trình tái cấu trúc P3 — Admission Advisory System

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) hoặc superpowers:executing-plans để thực thi plan này theo từng task. Các bước test dùng cú pháp checkbox (`- [ ]`) để theo dõi.

**Goal:** Thực hiện nhóm **P3 ("tái thiết kiến trúc lớn — scale")** của báo cáo audit `2026-06-16-architecture-audit.md` thành **10 PR nhỏ, review được độc lập**, mỗi PR giữ ứng dụng luôn chạy. Bao phủ 4 hạng mục audit: durable queue (S1/A3), connection pooling (D1), LLM I/O ra khỏi request path (A1), shared cooldown + cache embedding (S2/A4).

**Architecture:** P3 là nhóm rủi ro cao nhất, nên nguyên tắc cốt lõi là **additive-trước-khi-switch**: mỗi năng lực mới (pool, queue bền, cache) được đưa vào **sau một feature-flag mặc-định-tắt** hoặc một seam tiêm-phụ-thuộc, giữ nguyên 100% hành vi cũ; chỉ khi đã có bằng chứng (load test / chaos restart) mới lật cờ; cuối cùng mới **xóa** đường cũ. Không big-bang. **Bảo toàn mọi public API** (signature `connection_factory()`, `dispatcher.submit(...)`, route response shape) — ngoại lệ duy nhất là PR 10 đổi contract response, được tách riêng và **chỉ làm khi có phê duyệt rõ ràng**.

**Tech Stack:** Python 3, FastAPI + anyio/Starlette threadpool, psycopg2 + `psycopg2.pool.ThreadedConnectionPool` + pgvector, `google-genai` (SDK mới), `concurrent.futures.ThreadPoolExecutor`, pytest + monkeypatch/fake.

---

## Nguyên tắc chung cho mọi PR

- **Không `git push`** (theo CLAUDE.md). Chỉ `git commit` khi được yêu cầu, **không** trailer `Co-Authored-By` hay bất kỳ ghi nhận AI nào.
- Mỗi PR: chạy test xanh trước khi commit. Trên Linux: `.venv/bin/python -m pytest -q`; trên Windows: `.\.venv\Scripts\python.exe -m pytest -q`. Plan viết tắt là `pytest`.
- Test integration cần Docker DB (`docker compose up -d --wait db`); không có Docker thì các test đó tự skip — unit test vẫn phải xanh. pytest chạy trên DB `admission_test`, **không** đụng dev data (`tests/conftest.py::_isolate_test_db`).
- **Migration kế tiếp là `018`** (hiện có tới `017`). Mọi migration mới phải idempotent (`IF EXISTS`/`IF NOT EXISTS`/`ON CONFLICT`) khớp quy ước `001–017`.
- **Rollback mặc định cho mọi PR:** mỗi PR là 1 commit độc lập ⇒ rollback = `git revert <commit>` (hoặc `git reset --hard HEAD~1` nếu chưa hợp nhất). Các PR additive đều có flag tắt được tức thời (đổi env, không cần deploy lại code). Phần "Rollback strategy" của từng PR chỉ ghi thêm lưu ý đặc thù.
- **Feature flag** đọc từ env qua `ingestion/config/settings.py` (nguồn env tập trung của repo). Default của mọi flag mới = "hành vi cũ".

## Bảng tổng quan thứ tự (an toàn → rủi ro)

| PR | Tên | Mục audit | Rủi ro | Flag mặc định | Phụ thuộc |
|----|-----|-----------|--------|---------------|-----------|
| 1 | Cache embedding theo content-hash | A4 | Rất thấp | bật, size=512 (đặt 0 = tắt) | — |
| 2 | Reap orphaned runs lúc khởi động | A3/S1 | Thấp | bật (chỉ chạy 1 lần lúc start) | — |
| 3 | Bound queue + cấu hình worker cho dispatcher | A3 | Thấp | giữ 2 worker, queue cap mới | — |
| 4 | Right-size anyio request threadpool | A1 | Thấp | giữ 40 (cấu hình được) | — |
| 5 | `CooldownStore` injectable cho key pool | S2 | Thấp (refactor) | in-process (như cũ) | — |
| 6 | Hạ tầng connection pool (flag, **mặc định tắt**) | D1 | TB | `DB_POOL_ENABLED=false` | — |
| 7 | Bật connection pool mặc định | D1 | TB-Cao | `DB_POOL_ENABLED=true` | PR6 |
| 8 | Durable claim-based queue + poller (flag, **mặc định tắt**) | S1 | Cao | `ADVISORY_DURABLE_QUEUE=false` | PR2, PR3 |
| 9 | Lật mặc định sang durable queue + xóa đường executor in-process | S1/A3 | Cao | `ADVISORY_DURABLE_QUEUE=true` | PR8 |
| 10 | **(Cần phê duyệt)** Defer intent+profile LLM ra background | A1 | Cao (đổi contract) | `ADVISORY_DEFER_LLM=false` | PR8/PR9 |

> **Lưu ý quan trọng về A2 (timeout LLM):** đã được giải quyết ở P1 — `services/inference/providers/key_pool.py:48-55` truyền `http_options=types.HttpOptions(timeout=...)` cho mọi client. P3 **không** lặp lại việc này.

---

## PR 1 — Cache embedding theo content-hash (A4)

**Title:** `perf(inference): add process-level content-hash cache for embeddings`

**Goal:** Cùng một câu hỏi/đoạn văn bản hiện bị re-embed mỗi request (đốt quota free-tier 20 req/ngày). Thêm cache **cấp process** keyed theo `(model, dim, task_type, text)` ở `GeminiEmbedder.embed`: cache-hit bỏ qua call Gemini. Additive thuần — `EMBED_CACHE_SIZE=0` ⇒ tắt hoàn toàn, hành vi y hệt bản cũ.

**Files to modify:**
- `services/inference/embedder.py` — tách thân `embed` thành `_embed_uncached`, thêm lớp cache LRU module-level + `reset_embed_cache()` (cho test).
- `ingestion/config/settings.py` — thêm `EMBED_CACHE_SIZE = int(os.getenv("EMBED_CACHE_SIZE", 512))`.
- `tests/services/inference/test_embedder.py` — thêm test cache (tạo file nếu chưa có).

**Files to delete:** Không.

**Migration strategy:** Không có DB migration. Triển khai code:
1. Thêm setting:
   ```python
   # ingestion/config/settings.py
   # Cache embedding cấp process: cùng (model, dim, task_type, text) chỉ gọi Gemini 1 lần.
   # Đặt 0 để tắt hoàn toàn (hành vi cũ).
   EMBED_CACHE_SIZE = int(os.getenv("EMBED_CACHE_SIZE", 512))
   ```
2. Sửa `services/inference/embedder.py` — thêm đầu file:
   ```python
   import threading
   from collections import OrderedDict

   from ingestion.config.settings import (
       GEMINI_EMBEDDING_MODEL, EMBEDDING_DIM, EMBED_CACHE_SIZE,
   )

   _CACHE_LOCK = threading.Lock()
   _CACHE: "OrderedDict[tuple, list[float]]" = OrderedDict()


   def _cache_get(key):
       if EMBED_CACHE_SIZE <= 0:
           return None
       with _CACHE_LOCK:
           vec = _CACHE.get(key)
           if vec is not None:
               _CACHE.move_to_end(key)
           return vec


   def _cache_put(key, vec):
       if EMBED_CACHE_SIZE <= 0:
           return
       with _CACHE_LOCK:
           _CACHE[key] = vec
           _CACHE.move_to_end(key)
           while len(_CACHE) > EMBED_CACHE_SIZE:
               _CACHE.popitem(last=False)


   def reset_embed_cache():
       with _CACHE_LOCK:
           _CACHE.clear()
   ```
3. Đổi `embed` → giữ thân cũ thành `_embed_uncached`, thêm lớp cache phía trên (bảo toàn thứ tự kết quả, chỉ gọi API cho phần miss):
   ```python
   def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
       if EMBED_CACHE_SIZE <= 0:
           return self._embed_uncached(texts, task_type)
       results: list[list[float] | None] = [None] * len(texts)
       missing_idx: list[int] = []
       missing_texts: list[str] = []
       for i, t in enumerate(texts):
           key = (self.model, self.dim, task_type, t)
           cached = _cache_get(key)
           if cached is not None:
               results[i] = cached
           else:
               missing_idx.append(i)
               missing_texts.append(t)
       if missing_texts:
           fresh = self._embed_uncached(missing_texts, task_type)
           for j, vec in zip(missing_idx, fresh):
               results[j] = vec
               _cache_put((self.model, self.dim, task_type, texts[j]), vec)
       return results  # type: ignore[return-value]

   def _embed_uncached(self, texts: list[str], task_type: str) -> list[list[float]]:
       out: list[list[float]] = []
       for i in range(0, len(texts), self.batch_size):
           batch = texts[i:i + self.batch_size]
           response = self._pool.call(
               lambda client: client.models.embed_content(
                   model=self.model,
                   contents=batch,
                   config=types.EmbedContentConfig(
                       task_type=task_type,
                       output_dimensionality=self.dim,
                   ),
               ),
               context=" for embedding batch",
           )
           for emb in response.embeddings:
               out.append(l2_normalize(list(emb.values)))
       return out
   ```

**Test plan:**
- [ ] **Bước 1 — viết test fail:** thêm vào `tests/services/inference/test_embedder.py`:
  ```python
  from services.inference.embedder import GeminiEmbedder, reset_embed_cache

  class _CountingPool:
      def __init__(self):
          self.calls = 0
      def call(self, fn, *, context=""):
          self.calls += 1
          class _Emb:  # giả response.embeddings[i].values
              def __init__(self, v): self.values = v
          class _Resp:
              def __init__(self, n): self.embeddings = [_Emb([0.1, 0.2, 0.3]) for _ in range(n)]
          # contents đã bị đóng trong fn → đếm số phần tử qua closure không tiện;
          # trả 1 embedding/“lần text” bằng cách suy từ batch_size không cần thiết:
          return _Resp(1)

  def test_embed_caches_repeated_text():
      reset_embed_cache()
      pool = _CountingPool()
      emb = GeminiEmbedder(pool=pool, dim=3, batch_size=1)
      v1 = emb.embed(["xin chao"], task_type="RETRIEVAL_QUERY")
      v2 = emb.embed(["xin chao"], task_type="RETRIEVAL_QUERY")
      assert v1 == v2
      assert pool.calls == 1  # lần 2 lấy từ cache
  ```
- [ ] **Bước 2 — chạy để thấy fail:** `pytest tests/services/inference/test_embedder.py::test_embed_caches_repeated_text -v` → Expected: FAIL (`pool.calls == 2`).
- [ ] **Bước 3 — implement** theo Migration strategy ở trên.
- [ ] **Bước 4 — chạy lại:** cùng lệnh → Expected: PASS.
- [ ] **Bước 5 — regression off:** thêm test `EMBED_CACHE_SIZE=0` bypass:
  ```python
  def test_embed_cache_disabled(monkeypatch):
      import services.inference.embedder as e
      monkeypatch.setattr(e, "EMBED_CACHE_SIZE", 0)
      pool = _CountingPool()
      emb = GeminiEmbedder(pool=pool, dim=3, batch_size=1)
      emb.embed(["a"]); emb.embed(["a"])
      assert pool.calls == 2
  ```
  `pytest tests/services/inference/test_embedder.py -v` → PASS.
- [ ] **Bước 6 — full suite:** `pytest -q` → PASS.
- [ ] **Bước 7 — commit:**
  ```bash
  git add services/inference/embedder.py ingestion/config/settings.py tests/services/inference/test_embedder.py
  git commit -m "perf(inference): add process-level content-hash cache for embeddings"
  ```

**Rollback strategy:** Đặt `EMBED_CACHE_SIZE=0` (tức thời, không deploy) hoặc `git revert`. Cache chỉ là tối ưu đọc; tắt không mất dữ liệu.

---

## PR 2 — Reap orphaned runs lúc khởi động (A3/S1 — lưới an toàn)

**Title:** `fix(chat): reap orphaned advisory runs on startup`

**Goal:** Khi process restart giữa chừng, run đang `running`/`queued` trong `chat_advisory_runs` bị mất executor thực thi ⇒ session kẹt `running` mãi (recovery `_mark_failed` chỉ chạy khi có exception, không cho item bị drop). Thêm bước **reap lúc khởi động**: đánh các run "treo" thành `failed` + đăng message lỗi cho session, để UI thoát trạng thái quay-vòng. Additive, chạy 1 lần lúc start, không đụng happy-path.

**Files to modify:**
- `services/chat/repository.py` — thêm `reap_stale_runs() -> list[tuple[int, str]]` trả về `(run_id, session_token)` đã reap.
- `web/app.py` — gọi reaper trong startup hook.
- `tests/services/chat/test_repository.py` (integration) — test reap; `tests/web/test_app_startup.py` (mới) — test hook gọi reaper.

**Files to delete:** Không.

**Migration strategy:** Không cần migration — cột `status`, `started_at`, `error_text` đã có ở `009_chat_sessions.sql`. Triển khai:
1. Thêm method repository (idempotent, an toàn gọi nhiều lần):
   ```python
   def reap_stale_runs(self):
       """Đánh các run còn 'queued'/'running' (mồ côi sau restart) thành 'failed'
       và trả [(run_id, session_token)] để caller đăng message lỗi. Idempotent."""
       with self._cursor(commit=True) as cur:
           cur.execute(
               """
               UPDATE chat_advisory_runs r
               SET status = 'failed',
                   error_text = COALESCE(error_text, 'reaped on startup'),
                   completed_at = NOW()
               FROM chat_sessions s
               WHERE r.session_id = s.id
                 AND r.status IN ('queued', 'running')
               RETURNING r.id, s.session_token
               """
           )
           return [(row[0], row[1]) for row in cur.fetchall()]
   ```
2. Hàm dọn cấp service (đăng message + set session 'failed', tái dùng văn bản đã chuẩn ở `BaseRunDispatcher._mark_failed`):
   ```python
   # services/chat/startup.py  (mới)
   import logging
   from services.chat.repository import ChatSessionRepository

   logger = logging.getLogger(__name__)

   def reap_orphaned_runs(repository=None) -> int:
       repo = repository or ChatSessionRepository()
       reaped = repo.reap_stale_runs()
       for run_id, session_token in reaped:
           try:
               repo.append_message(
                   session_token, "assistant",
                   "Xin lỗi, quá trình phân tích bị gián đoạn. Bạn thử lại giúp mình nhé.",
                   "assistant_error",
               )
               repo.update_session_status(session_token, "failed")
           except Exception:
               logger.exception("reap: failed to finalize session %s", session_token)
       if reaped:
           logger.warning("reaped %d orphaned advisory run(s) on startup", len(reaped))
       return len(reaped)
   ```
3. Nối vào startup (`web/app.py`) — best-effort, không được làm app chết nếu DB chưa sẵn:
   ```python
   from services.chat.startup import reap_orphaned_runs

   def build_app() -> FastAPI:
       app = FastAPI(title="Student Advisory Chat")
       app.mount("/static", StaticFiles(directory="web/static"), name="static")
       app.include_router(system_router)
       app.include_router(chat_router)
       app.include_router(page_router)

       @app.on_event("startup")
       def _reap_on_startup():
           try:
               reap_orphaned_runs()
           except Exception:
               import logging
               logging.getLogger(__name__).exception("startup reap skipped")

       return app
   ```

**Test plan:**
- [ ] **Bước 1 — unit test service (fail trước):** `tests/services/chat/test_startup.py`:
  ```python
  from services.chat.startup import reap_orphaned_runs

  class FakeRepo:
      def __init__(self):
          self.stale = [(1, "tok-a"), (2, "tok-b")]
          self.messages = []
          self.statuses = []
      def reap_stale_runs(self):
          out, self.stale = self.stale, []
          return out
      def append_message(self, tok, role, content, kind="chat"):
          self.messages.append((tok, kind, content))
      def update_session_status(self, tok, status):
          self.statuses.append((tok, status))

  def test_reap_finalizes_each_orphan():
      repo = FakeRepo()
      n = reap_orphaned_runs(repository=repo)
      assert n == 2
      assert ("tok-a", "failed") in repo.statuses
      assert all(m[1] == "assistant_error" for m in repo.messages)

  def test_reap_idempotent_second_call_noop():
      repo = FakeRepo()
      reap_orphaned_runs(repository=repo)
      assert reap_orphaned_runs(repository=repo) == 0
  ```
- [ ] **Bước 2:** `pytest tests/services/chat/test_startup.py -v` → FAIL (module chưa tồn tại).
- [ ] **Bước 3 — implement** repository method + `startup.py` + hook.
- [ ] **Bước 4:** `pytest tests/services/chat/test_startup.py -v` → PASS.
- [ ] **Bước 5 — integration (có Docker):** trong `tests/services/chat/test_repository.py`, thêm test tạo run rồi `reap_stale_runs()` đánh nó `failed`:
  ```python
  def test_reap_stale_runs_marks_failed(repo, seeded_session):
      run_id = repo.create_run(seeded_session, {})
      reaped = repo.reap_stale_runs()
      assert any(rid == run_id for rid, _ in reaped)
      assert repo.get_run_status(run_id) == "failed"
  ```
  `pytest tests/services/chat/test_repository.py -q` (skip nếu không có Docker) → PASS.
- [ ] **Bước 6 — full suite:** `pytest -q` → PASS.
- [ ] **Bước 7 — commit:**
  ```bash
  git add services/chat/repository.py services/chat/startup.py web/app.py tests/services/chat/test_startup.py tests/services/chat/test_repository.py
  git commit -m "fix(chat): reap orphaned advisory runs on startup"
  ```

**Rollback strategy:** `git revert`. Reaper chỉ ghi `failed` cho run đã treo (không thể hoàn thành) ⇒ không mất dữ liệu hợp lệ. Nếu lo reap nhầm run đang chạy của replica khác, **không bật PR này khi đã có >1 replica chạy chung DB** cho tới khi có durable queue (PR8/9) — ghi rõ trong runbook.

---

## PR 3 — Bound queue + cấu hình worker cho dispatcher (A3)

**Title:** `fix(chat): bound dispatcher queue and make worker count configurable`

**Goal:** `ThreadPoolExecutor(max_workers=2)` + `executor.submit` không chặn ⇒ run thứ 3+ xếp hàng **vô hình** không giới hạn, không có backpressure. Thêm hàng đợi **có chặn** (bounded) và đếm worker cấu hình được; khi đầy thì từ chối tường minh (đăng message "đang quá tải") thay vì nuốt im. Bảo toàn API `submit(...)`.

**Files to modify:**
- `services/chat/base_dispatcher.py` — `__init__` nhận `max_workers`/`max_queue` từ settings; thêm `BoundedExecutor` wrapper + `_reject(session_token)`.
- `ingestion/config/settings.py` — `ADVISORY_RUN_WORKERS=int(os.getenv(...,2))`, `ADVISORY_RUN_QUEUE_MAX=int(os.getenv(...,32))`.
- `services/chat/run_dispatcher.py`, `services/chat/hybrid_dispatcher.py` — `submit` trả `bool` (đã nhận hay bị từ chối); xử lý reject.
- `tests/services/chat/test_base_dispatcher.py` — test bounded/reject.

**Files to delete:** Không.

**Migration strategy:**
1. Settings:
   ```python
   ADVISORY_RUN_WORKERS = int(os.getenv("ADVISORY_RUN_WORKERS", 2))
   ADVISORY_RUN_QUEUE_MAX = int(os.getenv("ADVISORY_RUN_QUEUE_MAX", 32))
   ```
2. `BoundedExecutor` trong `base_dispatcher.py` — bọc `ThreadPoolExecutor`, dùng `queue.Queue(maxsize)` để chặn/đếm; `submit` non-blocking trả `bool`:
   ```python
   import queue
   from concurrent.futures import ThreadPoolExecutor
   from ingestion.config.settings import ADVISORY_RUN_WORKERS, ADVISORY_RUN_QUEUE_MAX

   class BoundedExecutor:
       """ThreadPoolExecutor với hàng đợi đếm được. submit() trả False khi đầy
       (caller báo backpressure) thay vì xếp hàng vô hình."""
       def __init__(self, max_workers, max_queue):
           self._pool = ThreadPoolExecutor(max_workers=max_workers)
           self._sem = queue.Semaphore(max_queue) if hasattr(queue, "Semaphore") else __import__("threading").Semaphore(max_queue)

       def submit(self, fn, *args, **kwargs):
           if not self._sem.acquire(blocking=False):
               return False
           def _wrapped():
               try:
                   fn(*args, **kwargs)
               finally:
                   self._sem.release()
           self._pool.submit(_wrapped)
           return True
   ```
   > Dùng `threading.Semaphore` (import chuẩn). `max_queue` = số tác vụ in-flight tối đa (đang chạy + chờ).
3. `BaseRunDispatcher.__init__`:
   ```python
   def __init__(self, repository=None, executor=None):
       self.repository = repository or ChatSessionRepository()
       self.executor = executor or BoundedExecutor(ADVISORY_RUN_WORKERS, ADVISORY_RUN_QUEUE_MAX)

   def _reject(self, session_token: str):
       try:
           self.repository.append_message(
               session_token, "assistant",
               "Hệ thống đang xử lý nhiều yêu cầu, bạn vui lòng thử lại sau giây lát nhé.",
               "assistant_error",
           )
           self.repository.update_session_status(session_token, "failed")
       except Exception:
           logger.exception("failed to post reject message for session %s", session_token)
   ```
4. `RunDispatcher.submit`/`HybridDispatcher.submit` — kiểm tra giá trị trả về của `executor.submit`:
   ```python
   def submit(self, session_token, run_id, latest_user_message, profile_state,
              correction_note=None, closing_seed=0):
       accepted = self.executor.submit(
           self._execute, session_token, run_id, latest_user_message,
           profile_state, correction_note, closing_seed,
       )
       if not accepted:
           logger.warning("run queue full; rejecting run %s for %s", run_id, session_token)
           self.repository.complete_run(run_id, {"rejected": True}, "")
           self._reject(session_token)
       return accepted
   ```
   > `InlineExecutor` trong test trả `None` từ `submit`; sửa nó `return True` để giữ test cũ xanh (đã chấp nhận).

**Test plan:**
- [ ] **Bước 1 — sửa `InlineExecutor` test cũ trả `True`** trong `tests/services/chat/test_run_dispatcher.py` và `test_hybrid_dispatcher.py`:
  ```python
  class InlineExecutor:
      def submit(self, fn, *args, **kwargs):
          fn(*args, **kwargs)
          return True
  ```
- [ ] **Bước 2 — viết test reject (fail trước):** `tests/services/chat/test_base_dispatcher.py`:
  ```python
  from services.chat.run_dispatcher import RunDispatcher

  class FullExecutor:
      def submit(self, fn, *args, **kwargs):
          return False  # luôn đầy

  class RecordingRepo:
      def __init__(self): self.messages=[]; self.completed=None
      def complete_run(self, rid, res, ans): self.completed=(rid, res)
      def append_message(self, tok, role, content, kind="chat"): self.messages.append(kind)
      def update_session_status(self, tok, status): pass

  def test_submit_rejects_when_queue_full():
      repo = RecordingRepo()
      d = RunDispatcher(repository=repo, runner=lambda *a, **k: {"final_answer": "x"}, executor=FullExecutor())
      accepted = d.submit(session_token="t", run_id=5, latest_user_message="hi", profile_state=None)
      assert accepted is False
      assert "assistant_error" in repo.messages
      assert repo.completed[1] == {"rejected": True}
  ```
- [ ] **Bước 3:** `pytest tests/services/chat/test_base_dispatcher.py::test_submit_rejects_when_queue_full -v` → FAIL.
- [ ] **Bước 4 — implement** `BoundedExecutor`, `_reject`, sửa 2 `submit`.
- [ ] **Bước 5:** `pytest tests/services/chat/ -v` → PASS (gồm cả test cũ với `InlineExecutor` đã sửa).
- [ ] **Bước 6 — full suite:** `pytest -q` → PASS.
- [ ] **Bước 7 — commit:**
  ```bash
  git add services/chat/base_dispatcher.py services/chat/run_dispatcher.py services/chat/hybrid_dispatcher.py ingestion/config/settings.py tests/services/chat/
  git commit -m "fix(chat): bound dispatcher queue and make worker count configurable"
  ```

**Rollback strategy:** `git revert`. Mặc định `ADVISORY_RUN_QUEUE_MAX=32` đủ rộng để hành vi thực tế giống cũ ở tải thấp; muốn "vô hạn như cũ" tạm thời, đặt env rất lớn. Không có thay đổi schema.

---

## PR 4 — Right-size anyio request threadpool (A1, bước an toàn)

**Title:** `perf(web): make Starlette sync-route threadpool size configurable`

**Goal:** Mọi route trong `chat_api.py` là sync `def` ⇒ FastAPI chạy chúng trên anyio threadpool (mặc định 40). `POST /messages` giữ 1 worker suốt round-trip intent-router + profile-extract LLM. Cho phép **chỉnh kích thước threadpool** qua env để vận hành điều chỉnh theo tải, **không đổi contract**. Đây là bước A1 an toàn nhất (đổi sâu nằm ở PR 10, cần phê duyệt).

**Files to modify:**
- `web/app.py` — set anyio capacity limiter lúc startup.
- `ingestion/config/settings.py` — `WEB_THREADPOOL_SIZE=int(os.getenv("WEB_THREADPOOL_SIZE", 40))`.
- `tests/web/test_app_startup.py` — assert limiter được set đúng.

**Files to delete:** Không.

**Migration strategy:**
1. Setting:
   ```python
   WEB_THREADPOOL_SIZE = int(os.getenv("WEB_THREADPOOL_SIZE", 40))
   ```
2. `web/app.py` — set limiter trong startup hook (gộp chung hook với PR2 nếu PR2 đã merge):
   ```python
   @app.on_event("startup")
   def _configure_threadpool():
       try:
           import anyio.to_thread
           from ingestion.config.settings import WEB_THREADPOOL_SIZE
           anyio.to_thread.current_default_thread_limiter().total_tokens = WEB_THREADPOOL_SIZE
       except Exception:
           import logging
           logging.getLogger(__name__).exception("threadpool sizing skipped")
   ```

**Test plan:**
- [ ] **Bước 1 — test (fail trước):** `tests/web/test_app_startup.py`:
  ```python
  from fastapi.testclient import TestClient
  from web.app import build_app

  def test_threadpool_limiter_configured(monkeypatch):
      monkeypatch.setenv("WEB_THREADPOOL_SIZE", "12")
      import importlib, ingestion.config.settings as s
      importlib.reload(s)
      app = build_app()
      with TestClient(app):  # kích hoạt startup event
          import anyio.to_thread
          assert anyio.to_thread.current_default_thread_limiter().total_tokens == 12
  ```
  > Lưu ý: reload settings để env mới ăn vào; nếu repo cache giá trị, đọc env trực tiếp trong hook thay vì hằng module — chọn cách đọc trong hook để test ổn định.
- [ ] **Bước 2:** `pytest tests/web/test_app_startup.py -v` → FAIL.
- [ ] **Bước 3 — implement** (đọc `os.getenv("WEB_THREADPOOL_SIZE", "40")` ngay trong hook để né reload-cache).
- [ ] **Bước 4:** `pytest tests/web/test_app_startup.py -v` → PASS.
- [ ] **Bước 5 — smoke:** `pytest tests/web/ -q` → PASS (route cũ không đổi).
- [ ] **Bước 6 — full suite:** `pytest -q` → PASS.
- [ ] **Bước 7 — commit:**
  ```bash
  git add web/app.py ingestion/config/settings.py tests/web/test_app_startup.py
  git commit -m "perf(web): make Starlette sync-route threadpool size configurable"
  ```

**Rollback strategy:** `git revert` hoặc đặt `WEB_THREADPOOL_SIZE=40` (mặc định cũ của Starlette). Không đổi schema, không đổi contract.

---

## PR 5 — `CooldownStore` injectable cho key pool (S2)

**Title:** `refactor(inference): extract cooldown state behind an injectable CooldownStore`

**Goal:** `GeminiKeyPool._cooldown_until` là dict per-process; đa replica mỗi cái 1 view ⇒ vượt ngân sách 429. **Refactor** trạng thái cooldown ra sau interface `CooldownStore` (mặc định = `InProcessCooldownStore`, hành vi **y hệt hiện tại**). PR này **chưa** thêm Redis — chỉ mở seam để PR sau cắm shared store mà không sửa lại key pool. Bảo toàn hành vi.

**Files to modify:**
- `services/inference/providers/cooldown_store.py` (mới) — `CooldownStore` protocol + `InProcessCooldownStore`.
- `services/inference/providers/key_pool.py` — `GeminiKeyPool.__init__` nhận `cooldown_store=None`; `penalize`/`acquire` đọc-ghi qua store thay vì dict trực tiếp.
- `tests/services/inference/test_key_pool.py` — test store injectable.

**Files to delete:** Không.

**Migration strategy:**
1. `cooldown_store.py`:
   ```python
   import threading

   class InProcessCooldownStore:
       """Trạng thái cooldown cấp process (mặc định — hành vi cũ của GeminiKeyPool)."""
       def __init__(self):
           self._until: dict[str, float] = {}
           self._lock = threading.Lock()

       def is_cooling(self, key_id: str, now: float) -> bool:
           with self._lock:
               return self._until.get(key_id, 0.0) > now

       def penalize(self, key_id: str, until: float) -> None:
           with self._lock:
               self._until[key_id] = until
   ```
   > Protocol ngầm: bất kỳ object nào có `is_cooling(key_id, now)` + `penalize(key_id, until)`.
2. `key_pool.py` — `__init__` thêm `cooldown_store=None`; thay truy cập trực tiếp `self._cooldown_until`:
   ```python
   def __init__(self, keys, *, client_factory=_default_client_factory,
                cooldown_seconds=GEMINI_KEY_COOLDOWN_SECONDS, now=time.monotonic,
                cooldown_store=None):
       ...
       self._cooldown = cooldown_store or InProcessCooldownStore()
       # bỏ self._cooldown_until = {}
   ```
   `acquire()`:
   ```python
   if not self._cooldown.is_cooling(key, now):
       self._cursor = (idx + 1) % n
       return KeyHandle(key_id=key, client=self._client_for(key))
   ```
   `penalize()`:
   ```python
   def penalize(self, key_id: str, delay: float | None = None) -> None:
       cooldown = self._cooldown_seconds if delay is None else float(delay)
       self._cooldown.penalize(key_id, self._now() + cooldown)
   ```
   > Giữ `self._lock` cho `_cursor`/`_clients`; cooldown lock giờ nằm trong store.

**Test plan:**
- [ ] **Bước 1 — test seam (fail trước):** `tests/services/inference/test_key_pool.py`:
  ```python
  from services.inference.providers.key_pool import GeminiKeyPool

  class SpyStore:
      def __init__(self): self.penalized=[]; self.cooling=set()
      def is_cooling(self, key_id, now): return key_id in self.cooling
      def penalize(self, key_id, until): self.penalized.append(key_id)

  def test_pool_uses_injected_cooldown_store():
      store = SpyStore()
      pool = GeminiKeyPool(["k1", "k2"], cooldown_store=store, now=lambda: 0.0)
      pool.penalize("k1")
      assert store.penalized == ["k1"]
      store.cooling.add("k1")
      h = pool.acquire()
      assert h.key_id == "k2"  # k1 đang cooling theo store
  ```
- [ ] **Bước 2:** `pytest tests/services/inference/test_key_pool.py::test_pool_uses_injected_cooldown_store -v` → FAIL.
- [ ] **Bước 3 — implement** `cooldown_store.py` + sửa `key_pool.py`.
- [ ] **Bước 4:** cùng lệnh → PASS.
- [ ] **Bước 5 — regression:** `pytest tests/services/inference/ -v` → PASS (cooldown mặc định in-process giữ nguyên rotation/penalize).
- [ ] **Bước 6 — full suite:** `pytest -q` → PASS.
- [ ] **Bước 7 — commit:**
  ```bash
  git add services/inference/providers/cooldown_store.py services/inference/providers/key_pool.py tests/services/inference/test_key_pool.py
  git commit -m "refactor(inference): extract cooldown state behind an injectable CooldownStore"
  ```

**Rollback strategy:** `git revert`. Thuần refactor giữ hành vi; không flag, không schema. (Redis-backed store là PR tương lai ngoài phạm vi P3 lần này — chỉ làm khi thực sự chạy >1 replica.)

---

## PR 6 — Hạ tầng connection pool (flag, **mặc định tắt**) (D1)

**Title:** `feat(db): add ThreadedConnectionPool behind connection factories (flag-gated, default off)`

**Goal:** Mỗi method repository hiện mở 1 connection mới rồi `close()` — 1 lượt chat = hàng chục connect/teardown; bùng tải ⇒ cạn `max_connections`. Thêm hạ tầng pool dùng chung sau 3 connection factory (`get_db_connection`, `get_knowledge_db_connection`, `get_connection`) + seam release trong `cursor()`. **Mặc định tắt** (`DB_POOL_ENABLED=false`) ⇒ hành vi byte-for-byte như cũ. PR này chỉ thêm hạ tầng + đi dây; **chưa** bật.

**Files to modify:**
- `services/db/pool.py` (mới) — registry pool theo DSN + `lease()`/`release()`.
- `services/db/__init__.py` — `cursor()` finally đổi `conn.close()` → `release(conn)`.
- `services/chat/db.py`, `services/knowledge/db.py`, `ingestion/storage/db_connection.py` — factory dùng `lease()` khi flag bật, ngược lại `psycopg2.connect` như cũ.
- `ingestion/config/settings.py` — `DB_POOL_ENABLED`, `DB_POOL_MIN`, `DB_POOL_MAX`.
- `tests/services/db/test_pool.py` (mới).

**Files to delete:** Không.

**Migration strategy:** Không có DB migration (pool là client-side). Triển khai:
1. Settings:
   ```python
   DB_POOL_ENABLED = os.getenv("DB_POOL_ENABLED", "false").lower() == "true"
   DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", 1))
   DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", 10))
   ```
2. `services/db/pool.py` — pool theo từng DSN-key, gắn nhãn connection để `release()` biết trả về pool hay đóng thật:
   ```python
   import threading
   import psycopg2
   from psycopg2.pool import ThreadedConnectionPool
   from ingestion.config.settings import DB_POOL_MIN, DB_POOL_MAX

   _POOLS: dict[tuple, ThreadedConnectionPool] = {}
   _LOCK = threading.Lock()
   _TAG = "_advisory_pool_key"

   def _key(dsn: dict) -> tuple:
       return (dsn["host"], dsn["port"], dsn["database"], dsn["user"])

   def lease(dsn: dict):
       """Lấy connection từ pool (tạo pool nếu chưa có). Gắn nhãn để release() trả về đúng pool."""
       key = _key(dsn)
       with _LOCK:
           pool = _POOLS.get(key)
           if pool is None:
               pool = ThreadedConnectionPool(
                   DB_POOL_MIN, DB_POOL_MAX,
                   host=dsn["host"], port=dsn["port"], dbname=dsn["database"],
                   user=dsn["user"], password=dsn["password"],
               )
               _POOLS[key] = pool
       conn = pool.getconn()
       setattr(conn, _TAG, key)
       return conn

   def release(conn) -> None:
       """Trả connection về pool nếu nó được lease(); ngược lại đóng thật (đường không-pool)."""
       key = getattr(conn, _TAG, None)
       if key is None:
           conn.close()
           return
       with _LOCK:
           pool = _POOLS.get(key)
       if pool is None:
           conn.close()
       else:
           pool.putconn(conn)

   def close_all() -> None:
       with _LOCK:
           for pool in _POOLS.values():
               pool.closeall()
           _POOLS.clear()
   ```
3. `services/db/__init__.py` — `cursor()` finally dùng `release`:
   ```python
   from services.db.pool import release
   ...
       finally:
           release(conn)   # thay cho conn.close()
   ```
   > Connection không-pool (đường cũ) **không** có nhãn ⇒ `release()` gọi `conn.close()` y như trước. An toàn tuyệt đối khi flag tắt.
4. Mỗi factory — chọn pool hay không theo flag:
   ```python
   # services/chat/db.py
   from ingestion.config.settings import DB_CONFIG, DB_POOL_ENABLED

   def get_db_connection():
       if DB_POOL_ENABLED:
           from services.db.pool import lease
           return lease(DB_CONFIG)
       return psycopg2.connect(host=DB_CONFIG["host"], port=DB_CONFIG["port"],
                               database=DB_CONFIG["database"], user=DB_CONFIG["user"],
                               password=DB_CONFIG["password"])
   ```
   Lặp tương tự cho `services/knowledge/db.py` (`get_knowledge_db_connection`) và `ingestion/storage/db_connection.py` (`get_connection`). `ingestion/.../get_cursor` cũng đổi `finally: cur.close(); release(conn)` (import từ `services.db.pool`).

**Test plan:**
- [ ] **Bước 1 — test release-không-pool (fail trước):** `tests/services/db/test_pool.py`:
  ```python
  from services.db.pool import release

  class FakeConn:
      def __init__(self): self.closed=False
      def close(self): self.closed=True

  def test_release_closes_unpooled_connection():
      c = FakeConn()
      release(c)            # không có nhãn _advisory_pool_key
      assert c.closed is True
  ```
- [ ] **Bước 2:** `pytest tests/services/db/test_pool.py -v` → FAIL (module chưa có).
- [ ] **Bước 3 — implement** `pool.py` + đổi `cursor()` finally + factory.
- [ ] **Bước 4:** `pytest tests/services/db/test_pool.py -v` → PASS.
- [ ] **Bước 5 — test pool-roundtrip (có Docker):**
  ```python
  def test_lease_release_roundtrip_reuses_connection(monkeypatch):
      from ingestion.config.settings import DB_CONFIG
      import services.db.pool as p
      c1 = p.lease(DB_CONFIG); p.release(c1)
      c2 = p.lease(DB_CONFIG)
      assert c2 is c1   # ThreadedConnectionPool tái dùng
      p.release(c2); p.close_all()
  ```
  `pytest tests/services/db/test_pool.py -q` (skip nếu không Docker) → PASS.
- [ ] **Bước 6 — regression flag tắt:** `pytest -q` (mặc định `DB_POOL_ENABLED=false`) → PASS toàn bộ repository test cũ (chứng minh đường không-pool nguyên vẹn).
- [ ] **Bước 7 — commit:**
  ```bash
  git add services/db/pool.py services/db/__init__.py services/chat/db.py services/knowledge/db.py ingestion/storage/db_connection.py ingestion/config/settings.py tests/services/db/test_pool.py
  git commit -m "feat(db): add ThreadedConnectionPool behind connection factories (flag-gated, default off)"
  ```

**Rollback strategy:** `git revert`, hoặc đơn giản giữ `DB_POOL_ENABLED=false` (mặc định). Vì cờ tắt nghĩa là đường code mới không bao giờ chạy, rủi ro production = 0 cho tới PR7.

---

## PR 7 — Bật connection pool mặc định (D1)

**Title:** `feat(db): enable connection pooling by default`

**Goal:** Sau khi PR6 đã có hạ tầng pool và qua load test, **lật mặc định** `DB_POOL_ENABLED` sang `true` để hệ thống chịu tải đồng thời mà không cạn connection. Thay đổi tối thiểu (1 dòng default + cập nhật docs/`.env.example`), tách riêng để dễ revert độc lập với hạ tầng.

**Files to modify:**
- `ingestion/config/settings.py` — đổi default `DB_POOL_ENABLED` thành `"true"`.
- `.env.example` — thêm `DB_POOL_ENABLED`, `DB_POOL_MIN`, `DB_POOL_MAX` kèm chú thích.
- `QUICKSTART.md` / runbook — ghi chú pool + cách tắt khẩn cấp.

**Files to delete:** Không.

**Migration strategy:**
1. `settings.py`:
   ```python
   DB_POOL_ENABLED = os.getenv("DB_POOL_ENABLED", "true").lower() == "true"
   ```
2. `.env.example`:
   ```dotenv
   # Connection pool (psycopg2 ThreadedConnectionPool). Tắt khẩn cấp: DB_POOL_ENABLED=false
   DB_POOL_ENABLED=true
   DB_POOL_MIN=1
   DB_POOL_MAX=10
   ```
3. **Trước khi merge — load test bắt buộc** (ghi kết quả vào mô tả PR):
   - Bật DB cục bộ, đặt `DB_POOL_MAX=10`.
   - Bắn tải đồng thời vào `POST /api/sessions/{token}/messages` (ví dụ 50 client song song trong ~2 phút) bằng script `scripts/` tạm thời hoặc `hey`/`wrk`.
   - Kiểm `SELECT count(*) FROM pg_stat_activity WHERE datname='admission';` không vượt `DB_POOL_MAX + ingestion`. So sánh p95 latency với run `DB_POOL_ENABLED=false`.

**Test plan:**
- [ ] **Bước 1 — test default đã đổi:** thêm vào `tests/services/db/test_pool.py`:
  ```python
  def test_pool_enabled_by_default(monkeypatch):
      monkeypatch.delenv("DB_POOL_ENABLED", raising=False)
      import importlib, ingestion.config.settings as s
      importlib.reload(s)
      assert s.DB_POOL_ENABLED is True
  ```
  `pytest tests/services/db/test_pool.py::test_pool_enabled_by_default -v` → FAIL trước, PASS sau khi đổi default. (Nhớ reload lại settings về mặc định cuối test bằng fixture nếu cần.)
- [ ] **Bước 2 — full suite có Docker:** `docker compose up -d --wait db && pytest -q` → PASS (giờ chạy thật trên pool).
- [ ] **Bước 3 — load test thủ công** theo Migration strategy mục 3; dán số liệu vào PR.
- [ ] **Bước 4 — commit:**
  ```bash
  git add ingestion/config/settings.py .env.example QUICKSTART.md tests/services/db/test_pool.py
  git commit -m "feat(db): enable connection pooling by default"
  ```

**Rollback strategy:** Đặt `DB_POOL_ENABLED=false` (tức thời, không deploy) — đường không-pool của PR6 vẫn còn nguyên. Hoặc `git revert` riêng PR này mà không đụng hạ tầng PR6. Nếu thấy connection leak (pool cạn), `DB_POOL_MAX` lên cao tạm thời rồi điều tra `release()` được gọi đủ ở mọi `cursor()` exit.

---

## PR 8 — Durable claim-based queue + poller (flag, **mặc định tắt**) (S1)

**Title:** `feat(chat): durable claim-based advisory run queue (flag-gated, default off)`

**Goal:** Job state đang sống in-process trong executor; DB đánh `running` nhưng thực thi in-memory ⇒ không scale ngang (replica A không thấy job của B), restart = mất run. Thêm **hàng đợi bền** dựa trên chính bảng `chat_advisory_runs`: dispatch chỉ **enqueue** (`status='queued'`), một **poller** claim atomically bằng `UPDATE ... WHERE status='queued' ... FOR UPDATE SKIP LOCKED` rồi thực thi. **Mặc định tắt** (`ADVISORY_DURABLE_QUEUE=false`) ⇒ vẫn dùng executor cũ; chỉ thêm đường song song. Bảo toàn `dispatcher.submit(...)`.

**Files to modify:**
- `db/migrations/018_advisory_run_queue.sql` (mới) — index poll + cột `claimed_at`/`worker_id` (nullable, idempotent).
- `services/chat/repository.py` — `claim_next_queued_run() -> dict | None` (atomic claim), `enqueue_run(...)` (đảm bảo row ở `queued`).
- `services/chat/run_queue_worker.py` (mới) — vòng poll: claim → dựng payload → gọi `RunDispatcher._execute`/`HybridDispatcher._execute` (tái dùng logic thực thi, **không** sao chép).
- `services/chat/conversation_service.py::start_run` — khi flag bật: chỉ tạo run `queued` (không gọi `dispatcher.submit`); flag tắt: y như cũ.
- `web/app.py` — khi flag bật, khởi động 1 worker thread poller lúc startup.
- `ingestion/config/settings.py` — `ADVISORY_DURABLE_QUEUE`, `ADVISORY_QUEUE_POLL_SECONDS`.
- `tests/services/chat/test_run_queue_worker.py` (mới), `tests/services/chat/test_repository.py` (claim atomic).

**Files to delete:** Không (đường executor cũ còn nguyên — xóa ở PR9).

**Migration strategy:**
1. `db/migrations/018_advisory_run_queue.sql` (idempotent):
   ```sql
   -- 018_advisory_run_queue.sql
   -- Durable claim-based queue cho advisory run (audit S1). Cột claim + index poll.
   ALTER TABLE chat_advisory_runs ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
   ALTER TABLE chat_advisory_runs ADD COLUMN IF NOT EXISTS worker_id TEXT;
   CREATE INDEX IF NOT EXISTS idx_advisory_runs_queued
       ON chat_advisory_runs (created_at)
       WHERE status = 'queued';
   ```
2. Atomic claim trong repository (SKIP LOCKED ⇒ nhiều poller/replica không claim trùng):
   ```python
   def claim_next_queued_run(self, worker_id: str):
       """Claim 1 run 'queued' cũ nhất → 'running' atomically. Trả dict payload hoặc None."""
       with self._cursor(commit=True) as cur:
           cur.execute(
               """
               UPDATE chat_advisory_runs r
               SET status = 'running', started_at = NOW(),
                   claimed_at = NOW(), worker_id = %s
               WHERE r.id = (
                   SELECT id FROM chat_advisory_runs
                   WHERE status = 'queued'
                   ORDER BY created_at
                   FOR UPDATE SKIP LOCKED
                   LIMIT 1
               )
               RETURNING r.id, r.session_id, r.profile_snapshot_json
               """,
               (worker_id,),
           )
           row = cur.fetchone()
           if row is None:
               return None
           run_id, session_id = row[0], row[1]
           cur.execute("SELECT session_token FROM chat_sessions WHERE id = %s", (session_id,))
           token = cur.fetchone()[0]
           return {"run_id": run_id, "session_token": token, "profile_snapshot": row[2]}
   ```
   > **Lưu ý payload:** run cần `latest_user_message`/`correction_note`/`closing_seed` (advisory) hoặc `content`/`intent` (hybrid). Hiện `chat_advisory_runs` chỉ lưu `profile_snapshot_json`. Để durable thật, **mở rộng `create_run`/`enqueue_run` để snapshot thêm các tham số này vào một cột JSON `dispatch_args_json`** (thêm `ADD COLUMN IF NOT EXISTS dispatch_args_json JSONB` ở migration 018). Đây là điều kiện cần để poller dựng lại đủ input — ghi rõ trong PR.
3. `enqueue_run` = `create_run` hiện tại nhưng lưu cả `dispatch_args_json` và để `status='queued'` (đã là default cột). `start_run` khi `ADVISORY_DURABLE_QUEUE` bật: gọi `enqueue_run(...)` rồi **return** (poller lo phần còn lại); khi tắt: giữ nguyên `dispatcher.submit`.
4. `run_queue_worker.py` — vòng poll dùng `RunDispatcher`/`HybridDispatcher` đã có để thực thi (tái dùng `_execute`):
   ```python
   import logging, threading, time, json
   from ingestion.config.settings import ADVISORY_QUEUE_POLL_SECONDS
   from services.chat.repository import ChatSessionRepository
   from services.chat.run_dispatcher import RunDispatcher
   from services.chat.hybrid_dispatcher import HybridDispatcher

   logger = logging.getLogger(__name__)

   class RunQueueWorker:
       def __init__(self, worker_id: str, repository=None, run=None, hybrid=None,
                    poll_seconds: float = ADVISORY_QUEUE_POLL_SECONDS):
           self.worker_id = worker_id
           self.repository = repository or ChatSessionRepository()
           self.run = run or RunDispatcher(repository=self.repository)
           self.hybrid = hybrid or HybridDispatcher(repository=self.repository)
           self.poll_seconds = poll_seconds
           self._stop = threading.Event()

       def poll_once(self) -> bool:
           claimed = self.repository.claim_next_queued_run(self.worker_id)
           if claimed is None:
               return False
           args = claimed.get("dispatch_args") or {}
           if args.get("run_kind") == "hybrid":
               self.hybrid._execute(claimed["session_token"], claimed["run_id"],
                                    args["content"], args["profile_state"], args["intent"])
           else:
               self.run._execute(claimed["session_token"], claimed["run_id"],
                                 args["latest_user_message"], args["profile_state"],
                                 args.get("correction_note"), args.get("closing_seed", 0))
           return True

       def run_forever(self):
           while not self._stop.is_set():
               try:
                   worked = self.poll_once()
               except Exception:
                   logger.exception("queue worker poll failed")
                   worked = False
               if not worked:
                   self._stop.wait(self.poll_seconds)

       def stop(self):
           self._stop.set()
   ```
   > `_execute` đã tự `mark_run_running`; với poller, claim đã set `running` — chấp nhận double-set (idempotent, chỉ cập nhật timestamp). Có thể tinh chỉnh `_execute` nhận cờ `already_running=True` để bỏ `mark_run_running` — để PR9 làm khi hợp nhất đường.
5. `web/app.py` startup (chỉ khi flag bật):
   ```python
   @app.on_event("startup")
   def _start_queue_worker():
       from ingestion.config.settings import ADVISORY_DURABLE_QUEUE
       if not ADVISORY_DURABLE_QUEUE:
           return
       from services.chat.run_queue_worker import RunQueueWorker
       import socket, threading, os
       worker = RunQueueWorker(worker_id=f"{socket.gethostname()}-{os.getpid()}")
       app.state.queue_worker = worker
       threading.Thread(target=worker.run_forever, daemon=True).start()
   ```

**Test plan:**
- [ ] **Bước 1 — test poll_once dispatch advisory (fail trước):** `tests/services/chat/test_run_queue_worker.py`:
  ```python
  from services.chat.run_queue_worker import RunQueueWorker

  class OneShotRepo:
      def __init__(self):
          self._claim = {"run_id": 1, "session_token": "t",
                         "dispatch_args": {"run_kind": "advisory",
                                           "latest_user_message": "hi", "profile_state": None}}
      def claim_next_queued_run(self, worker_id):
          c, self._claim = self._claim, None
          return c

  class SpyDispatcher:
      def __init__(self): self.calls=[]
      def _execute(self, *a): self.calls.append(a)

  def test_poll_once_executes_claimed_advisory_run():
      repo = OneShotRepo()
      run = SpyDispatcher()
      w = RunQueueWorker("w1", repository=repo, run=run, hybrid=SpyDispatcher())
      assert w.poll_once() is True
      assert run.calls and run.calls[0][0] == "t" and run.calls[0][1] == 1
      assert w.poll_once() is False  # hết queue
  ```
- [ ] **Bước 2:** `pytest tests/services/chat/test_run_queue_worker.py -v` → FAIL.
- [ ] **Bước 3 — implement** migration 018, repository `claim_next_queued_run`/`enqueue_run`, `run_queue_worker.py`, nhánh flag trong `start_run`.
- [ ] **Bước 4:** `pytest tests/services/chat/test_run_queue_worker.py -v` → PASS.
- [ ] **Bước 5 — atomic claim (có Docker):** test 2 lần claim liên tiếp không trả trùng run:
  ```python
  def test_claim_is_atomic_no_double_dispatch(repo, seeded_session):
      rid = repo.enqueue_run(seeded_session, {}, {"run_kind": "advisory",
                                                  "latest_user_message": "x", "profile_state": None})
      first = repo.claim_next_queued_run("wA")
      second = repo.claim_next_queued_run("wB")
      assert first["run_id"] == rid
      assert second is None  # đã bị wA claim
  ```
  `pytest tests/services/chat/test_repository.py -q` (skip nếu không Docker) → PASS.
- [ ] **Bước 6 — regression flag tắt:** `pytest -q` (mặc định `ADVISORY_DURABLE_QUEUE=false`) → PASS (`test_start_run.py` cũ vẫn đi đường `dispatcher.submit`).
- [ ] **Bước 7 — chaos restart thủ công (có Docker):** bật flag, enqueue 1 run, kill process trước khi poller chạy, restart → run vẫn ở `queued`/được PR2 reap; với poller bật, run được nhặt và hoàn tất. Ghi lại quan sát.
- [ ] **Bước 8 — commit:**
  ```bash
  git add db/migrations/018_advisory_run_queue.sql services/chat/repository.py services/chat/run_queue_worker.py services/chat/conversation_service.py web/app.py ingestion/config/settings.py tests/services/chat/
  git commit -m "feat(chat): durable claim-based advisory run queue (flag-gated, default off)"
  ```

**Rollback strategy:** Đặt `ADVISORY_DURABLE_QUEUE=false` (tức thời) ⇒ về đường executor cũ; poller không khởi động. Migration 018 chỉ **thêm** cột nullable + index ⇒ forward-only an toàn, không cần down. Nếu cần gỡ hẳn: `git revert` code (migration cứ để lại, vô hại). Run đã `queued` mà tắt flag sẽ được PR2 reap lúc restart kế tiếp.

---

## PR 9 — Lật mặc định sang durable queue + xóa đường executor in-process (S1/A3)

**Title:** `refactor(chat): make durable queue the default and remove in-process executor dispatch`

**Goal:** Sau khi PR8 chứng minh durable queue qua chaos test, **lật mặc định** `ADVISORY_DURABLE_QUEUE=true` và **xóa đường fire-and-forget cũ** (executor `submit`, `BoundedExecutor`, singleton `get_run_dispatcher`/`get_hybrid_dispatcher`) — ưu tiên **xóa hơn giữ hai đường song song**. Đây là PR rủi ro cao nhất nhóm không-cần-phê-duyệt; làm cuối, sau khi mọi thứ khác ổn định.

**Files to modify:**
- `ingestion/config/settings.py` — default `ADVISORY_DURABLE_QUEUE=true`.
- `services/chat/conversation_service.py::start_run` — bỏ nhánh `dispatcher.submit`, chỉ còn `enqueue_run`.
- `services/chat/run_dispatcher.py`, `hybrid_dispatcher.py` — bỏ `submit`/singleton `get_*_dispatcher`/`BoundedExecutor` wiring; giữ `_execute` (poller dùng) → đổi tên thành `execute` (public cho worker).
- `services/chat/base_dispatcher.py` — bỏ `executor`/`BoundedExecutor`; giữ `repository` + `_mark_failed` + `_reject`.
- `.env.example`, runbook.

**Files to delete:**
- Không xóa file; **xóa code chết bên trong**: `BoundedExecutor` (chuyển vào lịch sử nếu không còn ai dùng), 2 singleton `@lru_cache get_*_dispatcher`, các test `test_run_dispatcher.py`/`test_hybrid_dispatcher.py` phần `InlineExecutor.submit` → viết lại quanh `execute`.

**Migration strategy:**
1. `settings.py`:
   ```python
   ADVISORY_DURABLE_QUEUE = os.getenv("ADVISORY_DURABLE_QUEUE", "true").lower() == "true"
   ```
2. `start_run` rút gọn (xóa toàn bộ nhánh dispatcher, chỉ enqueue):
   ```python
   def start_run(self, session_token, content, result) -> None:
       if not result.should_start_run:
           return
       dispatch_args = self._build_dispatch_args(content, result)  # advisory/hybrid args
       self.repository.enqueue_run(session_token, result.profile_state, dispatch_args)
   ```
   `_build_dispatch_args` đóng gói `run_kind`, `latest_user_message`/`content`, `correction_note`, `closing_seed` (tính từ `count_runs`), `intent` (hybrid) thành dict JSON-able.
3. Đổi `_execute` → `execute` ở cả 2 dispatcher; cập nhật `run_queue_worker.poll_once` gọi `.execute(...)`. Bỏ `submit`, `BoundedExecutor`, `get_run_dispatcher`/`get_hybrid_dispatcher`.
4. Vì `_execute` tự `mark_run_running` mà claim đã set running, thêm tham số `mark_running: bool = False` cho `execute` (poller truyền `False`) để tránh ghi timestamp thừa.

**Test plan:**
- [ ] **Bước 1 — đổi test dispatcher sang `execute`:** trong `tests/services/chat/test_run_dispatcher.py`, thay `dispatcher.submit(...)` bằng `dispatcher.execute(...)` (gọi trực tiếp, không executor). Ví dụ:
  ```python
  def test_dispatcher_completes_run_and_posts_result_message():
      repo = FakeRepository()
      dispatcher = RunDispatcher(repository=repo,
          runner=lambda profile_state, latest_user_message, trace_run_id=None,
                        correction_note=None, closing_seed=None: {"final_answer": "De xuat phu hop"})
      dispatcher.execute(session_token="session-123", run_id=7,
          latest_user_message="Em duoc 27 diem", profile_state=ChatProfileState(admission_year=2026, total_score=27.0))
      assert repo.completed[0] == 7
  ```
- [ ] **Bước 2 — test start_run enqueue-only (fail trước):** `tests/services/chat/test_start_run.py`:
  ```python
  def test_start_run_enqueues_without_dispatcher():
      class Repo:
          def __init__(self): self.enqueued=[]
          def enqueue_run(self, tok, profile, args): self.enqueued.append((tok, args)); return 1
      svc = ConversationService(repository=Repo())
      result = ConversationTurnResult(should_start_run=True, run_kind="advisory", profile_state={})
      svc.start_run("tok", "hi", result)
      assert svc.repository.enqueued[0][1]["run_kind"] == "advisory"
  ```
- [ ] **Bước 3:** `pytest tests/services/chat/test_start_run.py -v` → FAIL (start_run còn gọi dispatcher).
- [ ] **Bước 4 — implement** rút gọn `start_run`, đổi `execute`, xóa `submit`/singleton/`BoundedExecutor`.
- [ ] **Bước 5:** `pytest tests/services/chat/ -v` → PASS (toàn bộ test dispatcher + start_run + worker dùng `execute`).
- [ ] **Bước 6 — grep dọn:** `git grep -n "get_run_dispatcher\|get_hybrid_dispatcher\|\.submit(" services/chat web` → Expected: chỉ còn trong lịch sử/không còn caller sống. Sửa nốt nếu còn.
- [ ] **Bước 7 — integration end-to-end (có Docker):** `ADVISORY_DURABLE_QUEUE=true`, chạy 1 phiên chat thật → message enqueue, poller hoàn tất, snapshot trả `completed`. `pytest -q` → PASS.
- [ ] **Bước 8 — commit:**
  ```bash
  git add services/chat/ ingestion/config/settings.py .env.example tests/services/chat/
  git commit -m "refactor(chat): make durable queue the default and remove in-process executor dispatch"
  ```

**Rollback strategy:** Đặt `ADVISORY_DURABLE_QUEUE=false` **không còn tác dụng** sau PR này (đường executor đã xóa) ⇒ rollback = `git revert` PR9 (khôi phục đường executor) **rồi** đặt flag false. Vì rủi ro cao, giữ PR8 và PR9 ở 2 commit tách biệt để revert PR9 độc lập mà vẫn còn durable-queue (flag) của PR8. Khuyến nghị chạy song song flag bật ở canary ≥1 tuần trước khi merge PR9.

---

## PR 10 — (Cần phê duyệt) Defer intent+profile LLM ra background (A1, đổi contract)

**Title:** `feat(chat): defer intent routing & profile extraction off the request path`

**Goal:** Hoàn tất A1: `POST /messages` hiện chạy intent-router + profile-extract LLM **đồng bộ trong request**, giữ worker threadpool suốt round-trip LLM. Chuyển 2 call LLM này vào **background run** và trả response ngay (turn "đang xử lý"), để request path không còn I/O LLM. **PR này đổi contract response của `POST /messages`** (từ "kết quả phân loại tức thì" sang "ack + poll") ⇒ **vi phạm quy tắc 'preserve public API' và CHỈ thực hiện khi có phê duyệt rõ ràng của chủ dự án.** Nếu không được duyệt: bỏ qua PR này, A1 dừng ở PR4 (right-size threadpool) là chấp nhận được.

**Files to modify (nếu được duyệt):**
- `services/chat/conversation_service.py` — tách `handle_user_message` thành phần **không-LLM** (đồng bộ: tạo turn "processing", quyết định enqueue) và phần **LLM** (chạy trong run: intent + profile extract → quyết định route → tiếp tục advisory/hybrid/knowledge).
- `services/chat/run_queue_worker.py` — bước đầu của run giờ gồm cả classify + profile-extract.
- `web/routes/chat_api.py` — `post_message` trả turn "processing" + `run_id` để poll.
- `web/static/` JS — poll snapshot thay vì kỳ vọng kết quả phân loại tức thì.
- `tests/web/`, `tests/services/chat/` — cập nhật contract test.

**Files to delete:** Không (chỉ tái cấu trúc luồng).

**Migration strategy:**
1. **Lấy phê duyệt trước** (AskUserQuestion / xác nhận chủ dự án) về việc đổi contract `POST /messages`. Không duyệt ⇒ đóng PR.
2. Đặt sau cờ `ADVISORY_DEFER_LLM` (mặc định `false`) để bật dần và A/B với luồng cũ.
3. Tách `handle_user_message`:
   - **Sync (trong request):** chuẩn hóa input, kiểm reset, tạo bản ghi message user, trả `ConversationTurnResult(status="processing", run_id=...)` — **không** gọi LLM.
   - **Trong run (background, qua poller):** chạy intent router + `extract_profile`, rồi đi nhánh advisory/hybrid/knowledge như cũ, ghi kết quả qua `complete_run` + `append_message`.
4. Frontend đã poll `GET /api/sessions/{token}` cho kết quả run; mở rộng poll để hiển thị cả bước "đang phân loại".

**Test plan:**
- [ ] **Bước 1 — phê duyệt:** xác nhận chủ dự án đồng ý đổi contract. (Chặn cứng; không có thì dừng.)
- [ ] **Bước 2 — test sync path không gọi LLM (fail trước):**
  ```python
  def test_post_message_does_not_call_llm_inline(monkeypatch):
      called = {"llm": 0}
      # patch intent_router.classify & extract_profile để đếm
      ...
      svc.handle_user_message("tok", "tu van nganh CNTT")
      assert called["llm"] == 0  # LLM bị defer
  ```
- [ ] **Bước 3:** chạy → FAIL.
- [ ] **Bước 4 — implement** sau cờ `ADVISORY_DEFER_LLM`.
- [ ] **Bước 5 — contract test:** `POST /messages` trả `status="processing"` + `run_id`; snapshot poll cuối cùng trả kết quả đầy đủ. `pytest tests/web/ -v` → PASS.
- [ ] **Bước 6 — regression cờ tắt:** `ADVISORY_DEFER_LLM=false` → luồng cũ nguyên vẹn, `pytest -q` → PASS.
- [ ] **Bước 7 — commit (chỉ khi duyệt):**
  ```bash
  git add services/chat/ web/ tests/
  git commit -m "feat(chat): defer intent routing & profile extraction off the request path"
  ```

**Rollback strategy:** `ADVISORY_DEFER_LLM=false` (tức thời) ⇒ về luồng đồng bộ cũ; frontend cũ vẫn hoạt động vì giữ tương thích response. Hoặc `git revert`. Vì đây là thay đổi contract rủi ro cao, **không lật mặc định** trong P3 — chỉ giao năng lực sau cờ; việc lật mặc định là quyết định vận hành riêng.

---

## Self-Review (đối chiếu plan ↔ audit P3)

**Bao phủ 4 hạng mục P3 của §9:**
- **S1/A3 Durable queue + lost runs** → PR2 (reap), PR3 (bound queue), PR8 (durable claim-based), PR9 (lật mặc định + xóa executor). ✅
- **D1 Connection pooling** → PR6 (hạ tầng, flag tắt), PR7 (bật mặc định + load test). ✅
- **A1 LLM I/O ra khỏi request / async** → PR4 (right-size threadpool, an toàn), PR10 (defer LLM, cần phê duyệt). ✅ (A2 timeout đã xong ở P1 — ghi chú rõ.)
- **S2 shared cooldown + A4 cache** → PR1 (embed cache), PR5 (CooldownStore seam cho shared store tương lai). ✅

**Tuân thủ ràng buộc người dùng:**
- *No big-bang* → mỗi năng lực vào sau flag/seam, đổi-mặc-định và xóa tách thành PR riêng. ✅
- *Small reviewable PR* → 10 PR, mỗi PR ≤ ~6 file lõi. ✅
- *App luôn chạy* → flag mặc định = hành vi cũ ở PR1–8; PR7/9 chỉ lật sau bằng chứng. ✅
- *Prefer deletion* → PR9 xóa đường executor song song thay vì duy trì 2 đường. ✅
- *Preserve public API trừ khi được duyệt* → giữ `connection_factory()`, `submit→execute` nội bộ, route shape; ngoại lệ duy nhất PR10 tách riêng + gate phê duyệt. ✅
- *Mỗi PR có Title/Goal/Files modify/Files delete/Migration/Test/Rollback* → đủ. ✅
- *Sắp xếp an toàn → rủi ro* → bảng tổng quan + thứ tự PR1→PR10 theo rủi ro tăng dần. ✅

**Phụ thuộc & thứ tự:** PR7←PR6, PR8←{PR2,PR3}, PR9←PR8, PR10←{PR8/PR9}. Các PR còn lại độc lập, có thể làm song song.
