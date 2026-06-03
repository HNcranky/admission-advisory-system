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
from services.inference.models import InferenceError
from services.inference.providers.gemini_errors import (
    is_rotatable_error,
    parse_retry_delay,
)


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

    def release(self, key_id: str) -> None:
        """Reset cursor to key_id's position (undo a non-rotatable-error acquire)."""
        with self._lock:
            try:
                self._cursor = self._keys.index(key_id)
            except ValueError:
                pass

    def call(self, fn, *, context: str = ""):
        """Run fn(client) on a healthy key, rotating on key-specific failures.

        Shared rotation loop for every Gemini SDK call site (provider,
        embedder). On a rotatable error (429/auth/5xx) the key is cooled down
        and the next healthy key retries the same fn. A non-rotatable error
        (network, 4xx input) raises immediately without burning other keys.
        Raises InferenceError if no key is configured or all are cooling down.
        """
        if not self._keys:
            raise InferenceError("GEMINI_API_KEY is not configured")

        last_exc = None
        for _ in range(self.num_keys()):
            handle = self.acquire()
            if handle is None:  # every key is cooling down
                break
            try:
                return fn(handle.client)
            except Exception as exc:  # noqa: BLE001 - classify below
                if is_rotatable_error(exc):
                    self.penalize(handle.key_id, parse_retry_delay(exc))
                    last_exc = exc
                    continue
                # Not key-specific: switching keys won't help. Keep this key
                # first for the next request and surface the error.
                self.release(handle.key_id)
                raise InferenceError(
                    f"Gemini API call failed{context}: {exc!r}"
                ) from exc

        raise InferenceError(
            f"All Gemini API keys exhausted or cooling down{context}: {last_exc!r}"
        )


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
