import pytest

from services.inference.models import InferenceError
from services.inference.providers import key_pool as key_pool_module
from services.inference.providers.key_pool import (
    GeminiKeyPool,
    get_key_pool,
    load_gemini_keys,
    reset_key_pool,
)


class _ApiErr(Exception):
    """Mimics google.genai APIError: carries an int `code`."""

    def __init__(self, code):
        super().__init__(f"{code} error")
        self.code = code


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


# --- release ------------------------------------------------------------------

def test_release_resets_cursor_to_key_position():
    pool = GeminiKeyPool(["a", "b", "c"], client_factory=lambda k: k)
    pool.acquire()  # cursor advances to 1 (b)
    pool.release("a")  # reset cursor back to 0 (a)
    assert pool.acquire().key_id == "a"


def test_release_unknown_key_is_a_noop():
    pool = GeminiKeyPool(["a", "b"], client_factory=lambda k: k)
    pool.acquire()  # cursor at 1
    pool.release("nonexistent")  # should not raise or change cursor
    assert pool.acquire().key_id == "b"


# --- call (shared rotation loop) ----------------------------------------------

def test_call_returns_result_on_success():
    pool = GeminiKeyPool(["k1"], client_factory=lambda k: k)
    assert pool.call(lambda c: f"ok:{c}") == "ok:k1"


def test_call_rotates_to_next_key_on_rotatable_error():
    pool = GeminiKeyPool(["k1", "k2"], client_factory=lambda k: k)
    seen = []

    def fn(client):
        seen.append(client)
        if client == "k1":
            raise _ApiErr(429)
        return "done"

    assert pool.call(fn) == "done"
    assert seen == ["k1", "k2"]
    assert pool.acquire().key_id == "k2"  # k1 penalized → skipped


def test_call_raises_when_all_keys_rotatable_fail():
    pool = GeminiKeyPool(["k1", "k2"], client_factory=lambda k: k)

    def fn(client):
        raise _ApiErr(429)

    with pytest.raises(InferenceError, match="exhausted or cooling down"):
        pool.call(fn)
    assert pool.acquire() is None  # both penalized


def test_call_non_rotatable_error_raises_and_keeps_cursor():
    pool = GeminiKeyPool(["k1", "k2"], client_factory=lambda k: k)

    def fn(client):
        raise ValueError("network down")

    with pytest.raises(InferenceError):
        pool.call(fn)
    # cursor restored: k1 stays first healthy, k2 untouched
    assert pool.acquire().key_id == "k1"


def test_call_no_keys_raises_inference_error():
    pool = GeminiKeyPool([], client_factory=lambda k: k)
    with pytest.raises(InferenceError, match="not configured"):
        pool.call(lambda c: "x")


def test_call_includes_context_in_exhausted_message():
    pool = GeminiKeyPool(["k1"], client_factory=lambda k: k)

    def fn(client):
        raise _ApiErr(503)

    with pytest.raises(InferenceError, match="embedding batch"):
        pool.call(fn, context=" for embedding batch")


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
