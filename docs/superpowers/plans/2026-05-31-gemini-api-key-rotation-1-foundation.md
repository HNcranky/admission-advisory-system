# Gemini API Key Rotation — Plan 1/3: Foundation (Config + Error Classification)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Repo convention (overrides skill default):** This repo's CLAUDE.md says *never* run `git commit`/`git push` — the user commits. Every task therefore ends with a **Stage** step (`git add` only). Do NOT commit.

**Goal:** Đặt nền cho cơ chế xoay key — thêm setting cooldown + tài liệu env (Task 1) và lớp phân loại lỗi Gemini thuần (Task 2). Hai task này **độc lập với nhau** và không phụ thuộc plan khác.

**Dependencies:** Không có. Đây là plan nền tảng.
**Downstream:** Plan 2 (`key_pool`) cần `GEMINI_KEY_COOLDOWN_SECONDS` từ Task 1. Plan 3 (`provider`) cần `gemini_errors.py` từ Task 2.

**Tech Stack:** Python 3.12, `google-genai` SDK, pydantic v2, pytest. Chạy test bằng `./.venv/Scripts/python.exe -m pytest`.

**Spec:** `docs/superpowers/specs/2026-05-31-gemini-api-key-rotation-design.md`
**Overview:** `docs/superpowers/plans/2026-05-31-gemini-api-key-rotation.md`

---

## File Structure (plan này)

| File | Trách nhiệm | Hành động |
|---|---|---|
| `ingestion/config/settings.py` | Thêm `GEMINI_KEY_COOLDOWN_SECONDS`. | Modify |
| `.env.example` | Tài liệu `GEMINI_API_KEYS`, `GEMINI_KEY_COOLDOWN_SECONDS`. | Modify |
| `services/inference/providers/gemini_errors.py` | Phân loại lỗi Gemini (rotatable?) + parse `retryDelay`. Hàm thuần, không phụ thuộc SDK runtime. | Create |
| `tests/ingestion/test_settings_env.py` | Thêm 1 test cho setting cooldown. | Modify |
| `tests/services/inference/test_gemini_errors.py` | Test phân loại lỗi + parse delay. | Create |

**Quyết định thiết kế:** `load_gemini_keys()` (ở Plan 2) đọc `os.getenv` trực tiếp (không qua hằng số settings) để test monkeypatch env dễ; `settings.py` chỉ thêm `GEMINI_KEY_COOLDOWN_SECONDS` (dùng làm default cooldown của pool). `GEMINI_API_KEYS` chỉ cần tài liệu trong `.env.example`.

---

## Task 1: Config — cooldown setting + .env.example docs

**Files:**
- Modify: `ingestion/config/settings.py` (sau khối `GEMINI_API_KEY`, quanh dòng 44)
- Modify: `.env.example` (khối `# LLM`)
- Test: `tests/ingestion/test_settings_env.py` (thêm 1 test)

- [ ] **Step 1: Write the failing test**

Thêm vào cuối `tests/ingestion/test_settings_env.py`:

```python
def test_gemini_key_cooldown_seconds_default_is_positive_float():
    from ingestion.config import settings

    assert isinstance(settings.GEMINI_KEY_COOLDOWN_SECONDS, float)
    assert settings.GEMINI_KEY_COOLDOWN_SECONDS > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/Scripts/python.exe -m pytest tests/ingestion/test_settings_env.py::test_gemini_key_cooldown_seconds_default_is_positive_float -v`
Expected: FAIL — `AttributeError: module 'ingestion.config.settings' has no attribute 'GEMINI_KEY_COOLDOWN_SECONDS'`

- [ ] **Step 3: Add the constant**

Trong `ingestion/config/settings.py`, ngay sau dòng `GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")` (dòng 44):

```python
# --- Multi-key rotation (services/inference) -----------------------------
# Comma-separated extra keys, e.g. GEMINI_API_KEYS=key1,key2,key3. Combined with
# GEMINI_API_KEY (deduped) by services.inference.providers.key_pool.load_gemini_keys().
# When a key hits 429/auth/5xx it is "cooled down" for this many seconds (or the
# 429 retryDelay if larger) before the rotator will try it again.
GEMINI_KEY_COOLDOWN_SECONDS = float(os.getenv("GEMINI_KEY_COOLDOWN_SECONDS", 60))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/Scripts/python.exe -m pytest tests/ingestion/test_settings_env.py -v`
Expected: PASS (all tests in file)

- [ ] **Step 5: Document the new env vars in .env.example**

Thay khối `# LLM` trong `.env.example`:

```
# LLM
GEMINI_API_KEY=
# Optional: extra keys for automatic rotation when one is rate-limited (429).
# Comma-separated. Combined with GEMINI_API_KEY above (deduped).
GEMINI_API_KEYS=
# Seconds a key is skipped after a 429/auth/5xx before being retried (default 60).
GEMINI_KEY_COOLDOWN_SECONDS=60
```

- [ ] **Step 6: Stage changes (do NOT commit)**

```bash
git add ingestion/config/settings.py .env.example tests/ingestion/test_settings_env.py
```

---

## Task 2: Error classification — `gemini_errors.py`

**Files:**
- Create: `services/inference/providers/gemini_errors.py`
- Test: `tests/services/inference/test_gemini_errors.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/services/inference/test_gemini_errors.py`:

```python
from services.inference.providers.gemini_errors import (
    extract_status_code,
    is_rotatable_error,
    parse_retry_delay,
)


class FakeAPIError(Exception):
    """Mimics google.genai.errors.APIError: carries an int `code`."""

    def __init__(self, code, message=""):
        super().__init__(message or f"{code} error")
        self.code = code


# Realistic 429 string seen in production logs.
_REAL_429 = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': "
    "'You exceeded your current quota. Please retry in 26.777807406s.', "
    "'status': 'RESOURCE_EXHAUSTED', 'details': [{'@type': "
    "'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '26s'}]}}"
)


def test_extract_status_code_reads_code_attribute():
    assert extract_status_code(FakeAPIError(429)) == 429
    assert extract_status_code(FakeAPIError(503)) == 503


def test_extract_status_code_falls_back_to_string_scan():
    assert extract_status_code(RuntimeError("429 RESOURCE_EXHAUSTED")) == 429


def test_extract_status_code_returns_none_when_absent():
    assert extract_status_code(ValueError("boom")) is None


def test_is_rotatable_for_quota_auth_and_server_errors():
    assert is_rotatable_error(FakeAPIError(429)) is True
    assert is_rotatable_error(FakeAPIError(401)) is True
    assert is_rotatable_error(FakeAPIError(403)) is True
    assert is_rotatable_error(FakeAPIError(500)) is True
    assert is_rotatable_error(FakeAPIError(503)) is True


def test_is_not_rotatable_for_client_input_and_unknown_errors():
    assert is_rotatable_error(FakeAPIError(400)) is False
    assert is_rotatable_error(FakeAPIError(404)) is False
    assert is_rotatable_error(ValueError("network down")) is False


def test_parse_retry_delay_from_retrydelay_field():
    assert parse_retry_delay(RuntimeError("...'retryDelay': '26s'...")) == 26.0


def test_parse_retry_delay_from_retry_in_phrase():
    assert parse_retry_delay(RuntimeError("Please retry in 26.7s.")) == 26.7


def test_parse_retry_delay_on_real_429_payload():
    assert parse_retry_delay(FakeAPIError(429, _REAL_429)) == 26.0


def test_parse_retry_delay_returns_none_when_absent():
    assert parse_retry_delay(FakeAPIError(429, "quota exceeded")) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/services/inference/test_gemini_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.inference.providers.gemini_errors'`

- [ ] **Step 3: Write the implementation**

Create `services/inference/providers/gemini_errors.py`:

```python
"""Classify google-genai exceptions for key rotation.

google.genai.errors.APIError (and ClientError/ServerError) carry an int `code`
HTTP status. We treat 429 (quota), 401/403 (auth) and 5xx (server) as
"key-specific" — worth retrying on a different key. Anything else (e.g. a plain
network failure or a 4xx input error) is not helped by switching keys.
"""

import re

ROTATABLE_STATUSES = frozenset({401, 403, 429})

_STATUS_RE = re.compile(r"\b([1-5]\d{2})\b")
# 'retryDelay': '26s'  /  retryDelay=26s
_RETRY_DELAY_RE = re.compile(
    r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)\s*s", re.IGNORECASE
)
# "Please retry in 26.7s"
_RETRY_IN_RE = re.compile(r"retry in\s+(\d+(?:\.\d+)?)\s*s", re.IGNORECASE)


def extract_status_code(exc) -> int | None:
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    match = _STATUS_RE.search(str(exc))
    return int(match.group(1)) if match else None


def is_rotatable_error(exc) -> bool:
    status = extract_status_code(exc)
    if status is None:
        return False
    return status in ROTATABLE_STATUSES or 500 <= status < 600


def parse_retry_delay(exc) -> float | None:
    text = str(exc)
    for pattern in (_RETRY_DELAY_RE, _RETRY_IN_RE):
        match = pattern.search(text)
        if match:
            return float(match.group(1))
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/services/inference/test_gemini_errors.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Stage changes (do NOT commit)**

```bash
git add services/inference/providers/gemini_errors.py tests/services/inference/test_gemini_errors.py
```

---

## Definition of done (Plan 1)

- [ ] `settings.GEMINI_KEY_COOLDOWN_SECONDS` tồn tại, là `float > 0`; `.env.example` ghi chú `GEMINI_API_KEYS` + `GEMINI_KEY_COOLDOWN_SECONDS`.
- [ ] `services/inference/providers/gemini_errors.py` cung cấp `extract_status_code`, `is_rotatable_error`, `parse_retry_delay`; 10 test xanh.
- [ ] Tất cả thay đổi đã `git add` (chưa commit).

➡️ Tiếp theo: **Plan 2** — `docs/superpowers/plans/2026-05-31-gemini-api-key-rotation-2-key-pool.md`.
