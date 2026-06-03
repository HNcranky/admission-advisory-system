# Gemini API Key Rotation — Plan Overview (Index)

> **Đã tách thành 3 sub-plan theo lớp phụ thuộc.** File này là overview chung;
> thực thi theo thứ tự các sub-plan bên dưới. Mỗi sub-plan tự chứa (file structure,
> task, test, lệnh chạy) và dùng checkbox `- [ ]` để theo dõi.

> **Repo convention (overrides skill default):** This repo's CLAUDE.md says *never*
> run `git commit`/`git push` — the user commits. Mọi task kết thúc bằng bước
> **Stage** (`git add` only). Do NOT commit.

**Goal:** Cho phép cấu hình nhiều Gemini API key và tự động xoay vòng sang key khỏe kế tiếp khi một key bị rate-limit (429) / auth (401/403) / server (5xx), với cooldown per-key.

**Architecture:** Một `GeminiKeyPool` singleton cấp process giữ danh sách key + cache `genai.Client` theo key + bản đồ cooldown + `Lock`. `GeminiProvider.generate()` lặp lấy key khỏe từ pool, gọi Gemini, gặp lỗi gắn-với-key thì penalize key đó và thử key kế; hết key khỏe → raise `InferenceError` (degrade graceful như cũ). `LLMGateway` và `ModelRegistry` không đổi.

**Tech Stack:** Python 3.12, `google-genai` SDK, pydantic v2, pytest. Chạy test bằng `./.venv/Scripts/python.exe -m pytest`.

**Spec:** `docs/superpowers/specs/2026-05-31-gemini-api-key-rotation-design.md`

---

## Sub-plans (thực thi theo thứ tự)

| # | Plan | Nội dung (task gốc) | Phụ thuộc |
|---|---|---|---|
| 1 | [`...-1-foundation.md`](2026-05-31-gemini-api-key-rotation-1-foundation.md) | Config cooldown + `.env.example` (Task 1) · Error classification `gemini_errors.py` (Task 2) | — |
| 2 | [`...-2-key-pool.md`](2026-05-31-gemini-api-key-rotation-2-key-pool.md) | `GeminiKeyPool` + loader + singleton (Task 3) | Plan 1 |
| 3 | [`...-3-provider.md`](2026-05-31-gemini-api-key-rotation-3-provider.md) | Provider failover rewrite (Task 4) · Regression + smoke + spec status (Task 5) | Plan 1, 2 |

Trong Plan 1, Task 1 và Task 2 độc lập với nhau → có thể làm song song / đổi thứ tự.

---

## File Structure (toàn bộ feature)

| File | Trách nhiệm | Hành động | Plan |
|---|---|---|---|
| `ingestion/config/settings.py` | Thêm `GEMINI_KEY_COOLDOWN_SECONDS`. | Modify | 1 |
| `.env.example` | Tài liệu `GEMINI_API_KEYS`, `GEMINI_KEY_COOLDOWN_SECONDS`. | Modify | 1 |
| `services/inference/providers/gemini_errors.py` | Phân loại lỗi Gemini (rotatable?) + parse `retryDelay`. Hàm thuần, không phụ thuộc SDK runtime. | Create | 1 |
| `services/inference/providers/key_pool.py` | `load_gemini_keys()`, `GeminiKeyPool`, singleton `get_key_pool()`/`reset_key_pool()`. | Create | 2 |
| `services/inference/providers/gemini_provider.py` | `generate()` xoay key qua pool; tách `_call()` + `_build_result()`. | Modify | 3 |
| `tests/ingestion/test_settings_env.py` | Test setting cooldown. | Modify | 1 |
| `tests/services/inference/test_gemini_errors.py` | Test phân loại lỗi + parse delay. | Create | 1 |
| `tests/services/inference/test_key_pool.py` | Test loader, round-robin, cooldown, singleton, thread-safe. | Create | 2 |
| `tests/services/inference/test_gemini_provider.py` | Viết lại sang inject pool/client_factory + test failover. | Modify | 3 |
| `docs/superpowers/specs/2026-05-31-gemini-api-key-rotation-design.md` | Đổi `Status: Draft → Implemented`. | Modify | 3 |

**Quyết định thiết kế:** `load_gemini_keys()` đọc `os.getenv` trực tiếp (không qua hằng số settings) để test monkeypatch env dễ; `settings.py` chỉ thêm `GEMINI_KEY_COOLDOWN_SECONDS` (dùng làm default cooldown của pool). `GEMINI_API_KEYS` chỉ cần tài liệu trong `.env.example`.

---

## How the user enables it

In `.env`:
```
GEMINI_API_KEYS=key_one,key_two,key_three
```
(Keep or drop `GEMINI_API_KEY`; both are merged.) Restart uvicorn. When `key_one`
hits 429, the rotator parses its `retryDelay`, cools `key_one` down, and retries
the same request on `key_two` — transparently to every gateway call site.

---

## Self-Review notes

- **Spec coverage:** multi-key config (Plan 1 Task 1, Plan 2 Task 3) ✓; failover same-request + cooldown (Plan 3 Task 4) ✓; 429/auth/5xx classification + retryDelay parse (Plan 1 Task 2) ✓; all-cooling → InferenceError degrade (Plan 3 `test_raises_when_all_keys_rate_limited`) ✓; network → raise immediately (Plan 3 `test_non_rotatable_error...`) ✓; backward-compat single key (Plan 3 `test_api_key_constructor...`) ✓; gateway/registry untouched (Plan 3 factory suite) ✓; thread-safe (Plan 2 concurrency test) ✓.
- **Type consistency:** `KeyHandle(key_id, client)`, `GeminiKeyPool.acquire()→KeyHandle|None`, `penalize(key_id, delay=None)`, `has_keys()/num_keys()`, `load_gemini_keys()→list[str]`, `get_key_pool()/reset_key_pool()` dùng nhất quán xuyên Plan 2–3.
- **No placeholders:** mỗi step có code/lệnh chạy được và expected output.
