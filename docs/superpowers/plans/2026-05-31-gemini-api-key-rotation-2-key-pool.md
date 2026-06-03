# Gemini API Key Rotation — Plan 2/3: Key Pool

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Repo convention (overrides skill default):** This repo's CLAUDE.md says *never* run `git commit`/`git push` — the user commits. Every task therefore ends with a **Stage** step (`git add` only). Do NOT commit.

**Goal:** Xây `GeminiKeyPool` — singleton cấp process giữ danh sách key + cache `genai.Client` theo key + bản đồ cooldown + `Lock`, cùng loader `load_gemini_keys()` và accessor `get_key_pool()`/`reset_key_pool()`.

**Dependencies:** **Plan 1** phải xong trước — `key_pool.py` import `GEMINI_KEY_COOLDOWN_SECONDS` từ `ingestion/config/settings.py` (Task 1) làm cooldown mặc định.
**Downstream:** Plan 3 (`provider`) inject pool này vào `GeminiProvider`.

**Tech Stack:** Python 3.12, `google-genai` SDK, pydantic v2, pytest. Chạy test bằng `./.venv/Scripts/python.exe -m pytest`.

**Spec:** `docs/superpowers/specs/2026-05-31-gemini-api-key-rotation-design.md`
**Overview:** `docs/superpowers/plans/2026-05-31-gemini-api-key-rotation.md`

---

## File Structure (plan này)

| File | Trách nhiệm | Hành động |
|---|---|---|
| `services/inference/providers/key_pool.py` | `load_gemini_keys()`, `GeminiKeyPool`, singleton `get_key_pool()`/`reset_key_pool()`. | Create |
| `tests/services/inference/test_key_pool.py` | Test loader, round-robin, cooldown, singleton, thread-safe. | Create |

---

## Task 3: Key pool — `key_pool.py`

**Files:**
- Create: `services/inference/providers/key_pool.py`
- Test: `tests/services/inference/test_key_pool.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/services/inference/test_key_pool.py`:

```python
import pytest

from services.inference.providers import key_pool as key_pool_module
from services.inference.providers.key_pool import (
    GeminiKeyPool,
    get_key_pool,
    load_gemini_keys,
    reset_key_pool,
)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _factory_counting(calls):
    def factory(api_key):
        calls.append(api_key)
        return f"client-for-{api_key}"
    return factory


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_key_pool()
    yield
    reset_key_pool()


# --- load_gemini_keys ---------------------------------------------------------

def test_load_gemini_keys_combines_csv_and_single_and_dedupes(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "k1, k2 , ,k1")
    monkeypatch.setenv("GEMINI_API_KEY", "k3")
    assert load_gemini_keys() == ["k1", "k2", "k3"]


def test_load_gemini_keys_single_key_only(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "solo")
    assert load_gemini_keys() == ["solo"]


def test_load_gemini_keys_empty_when_unset(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert load_gemini_keys() == []


# --- construction / dedupe ----------------------------------------------------

def test_pool_dedupes_and_drops_blanks():
    pool = GeminiKeyPool(["a", " a ", "", "b"], client_factory=lambda k: k)
    assert pool.num_keys() == 2
    assert pool.has_keys() is True


def test_empty_pool_has_no_keys():
    pool = GeminiKeyPool([], client_factory=lambda k: k)
    assert pool.has_keys() is False
    assert pool.acquire() is None


# --- round-robin & client caching --------------------------------------------

def test_acquire_round_robins_across_keys():
    calls = []
    pool = GeminiKeyPool(["a", "b", "c"], client_factory=_factory_counting(calls))
    assert [pool.acquire().key_id for _ in range(4)] == ["a", "b", "c", "a"]


def test_acquire_caches_client_per_key():
    calls = []
    pool = GeminiKeyPool(["a", "b"], client_factory=_factory_counting(calls))
    for _ in range(4):
        pool.acquire()
    assert sorted(calls) == ["a", "b"]  # each key built exactly once


def test_acquire_returns_handle_with_client():
    pool = GeminiKeyPool(["a"], client_factory=lambda k: f"client-{k}")
    handle = pool.acquire()
    assert handle.key_id == "a"
    assert handle.client == "client-a"


# --- cooldown -----------------------------------------------------------------

def test_penalize_skips_key_until_cooldown_elapses():
    clock = FakeClock()
    pool = GeminiKeyPool(["a", "b"], client_factory=lambda k: k,
                         cooldown_seconds=30, now=clock)
    pool.penalize("a")                       # a cooling until t=30
    assert [pool.acquire().key_id for _ in range(3)] == ["b", "b", "b"]
    clock.t = 30.0                           # cooldown elapsed (<=)
    assert pool.acquire().key_id in {"a", "b"}
    seen = {pool.acquire().key_id for _ in range(6)}
    assert seen == {"a", "b"}


def test_penalize_uses_explicit_delay_over_default():
    clock = FakeClock()
    pool = GeminiKeyPool(["a"], client_factory=lambda k: k,
                         cooldown_seconds=10, now=clock)
    pool.penalize("a", delay=100)
    clock.t = 50.0
    assert pool.acquire() is None            # still cooling (100 > 50)
    clock.t = 100.0
    assert pool.acquire().key_id == "a"


def test_acquire_returns_none_when_all_cooling():
    clock = FakeClock()
    pool = GeminiKeyPool(["a", "b"], client_factory=lambda k: k,
                         cooldown_seconds=30, now=clock)
    pool.penalize("a")
    pool.penalize("b")
    assert pool.acquire() is None


# --- singleton ----------------------------------------------------------------

def test_get_key_pool_is_singleton(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "solo")
    first = get_key_pool()
    assert get_key_pool() is first


def test_reset_key_pool_rebuilds(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "solo")
    first = get_key_pool()
    reset_key_pool()
    assert get_key_pool() is not first


# --- thread safety (smoke) ----------------------------------------------------

def test_concurrent_acquire_only_returns_valid_keys():
    import threading

    pool = GeminiKeyPool(["a", "b", "c"], client_factory=lambda k: k)
    results = []
    lock = threading.Lock()

    def worker():
        local = [pool.acquire().key_id for _ in range(50)]
        with lock:
            results.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert set(results) <= {"a", "b", "c"}
    assert len(results) == 8 * 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/Scripts/python.exe -m pytest tests/services/inference/test_key_pool.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.inference.providers.key_pool'`

- [ ] **Step 3: Write the implementation**

Create `services/inference/providers/key_pool.py`:

```python
"""Process-level pool of Gemini API keys with per-key cooldown.

build_default_gateway() is called fresh per request, so cooldown state cannot
live on a provider/gateway instance — it lives in a module-level singleton here.
Thread-safe: advisory runs execute in a background ThreadPoolExecutor.
"""

import os
import threading
import time
from dataclasses import dataclass

from google import genai

from ingestion.config.settings import GEMINI_KEY_COOLDOWN_SECONDS


@dataclass
class KeyHandle:
    key_id: str
    client: object


def load_gemini_keys() -> list[str]:
    """GEMINI_API_KEYS (CSV) + GEMINI_API_KEY, stripped, blanks dropped, deduped
    (order preserved). Read live from the environment for testability."""
    raw = os.getenv("GEMINI_API_KEYS", "").split(",")
    raw.append(os.getenv("GEMINI_API_KEY", ""))
    ordered: list[str] = []
    seen: set[str] = set()
    for key in raw:
        key = key.strip()
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return ordered


def _default_client_factory(api_key: str):
    return genai.Client(api_key=api_key)


class GeminiKeyPool:
    def __init__(
        self,
        keys,
        *,
        client_factory=_default_client_factory,
        cooldown_seconds: float = GEMINI_KEY_COOLDOWN_SECONDS,
        now=time.monotonic,
    ):
        ordered: list[str] = []
        seen: set[str] = set()
        for key in keys:
            key = (key or "").strip()
            if key and key not in seen:
                seen.add(key)
                ordered.append(key)
        self._keys = ordered
        self._client_factory = client_factory
        self._cooldown_seconds = float(cooldown_seconds)
        self._now = now
        self._clients: dict[str, object] = {}
        self._cooldown_until: dict[str, float] = {}
        self._cursor = 0
        self._lock = threading.Lock()

    def has_keys(self) -> bool:
        return bool(self._keys)

    def num_keys(self) -> int:
        return len(self._keys)

    def _client_for(self, key: str):
        client = self._clients.get(key)
        if client is None:
            client = self._client_factory(key)
            self._clients[key] = client
        return client

    def acquire(self) -> KeyHandle | None:
        with self._lock:
            n = len(self._keys)
            if n == 0:
                return None
            now = self._now()
            for offset in range(n):
                idx = (self._cursor + offset) % n
                key = self._keys[idx]
                if self._cooldown_until.get(key, 0.0) <= now:
                    self._cursor = (idx + 1) % n
                    return KeyHandle(key_id=key, client=self._client_for(key))
            return None

    def penalize(self, key_id: str, delay: float | None = None) -> None:
        with self._lock:
            cooldown = self._cooldown_seconds if delay is None else float(delay)
            self._cooldown_until[key_id] = self._now() + cooldown


_POOL: GeminiKeyPool | None = None
_POOL_INIT_LOCK = threading.Lock()


def get_key_pool() -> GeminiKeyPool:
    global _POOL
    if _POOL is None:
        with _POOL_INIT_LOCK:
            if _POOL is None:
                _POOL = GeminiKeyPool(load_gemini_keys())
    return _POOL


def reset_key_pool() -> None:
    global _POOL
    with _POOL_INIT_LOCK:
        _POOL = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./.venv/Scripts/python.exe -m pytest tests/services/inference/test_key_pool.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Stage changes (do NOT commit)**

```bash
git add services/inference/providers/key_pool.py tests/services/inference/test_key_pool.py
```

---

## Definition of done (Plan 2)

- [ ] `load_gemini_keys()` gộp CSV + single key, strip/dedupe giữ thứ tự.
- [ ] `GeminiKeyPool` round-robin, cache client/key, cooldown per-key, thread-safe; `acquire()→KeyHandle|None`, `penalize(key_id, delay=None)`, `has_keys()/num_keys()`.
- [ ] `get_key_pool()` singleton double-checked; `reset_key_pool()` rebuild. 15 test xanh.
- [ ] Tất cả thay đổi đã `git add` (chưa commit).

➡️ Tiếp theo: **Plan 3** — `docs/superpowers/plans/2026-05-31-gemini-api-key-rotation-3-provider.md`.
