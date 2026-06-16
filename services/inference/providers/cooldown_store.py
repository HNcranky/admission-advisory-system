import threading


class InProcessCooldownStore:
    """Per-process cooldown state for GeminiKeyPool (default — matches old behaviour).

    Any object that implements is_cooling(key_id, now) + penalize(key_id, until)
    can be injected into GeminiKeyPool as an alternative (e.g. a Redis-backed store
    for multi-replica deployments)."""

    def __init__(self):
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_cooling(self, key_id: str, now: float) -> bool:
        with self._lock:
            return self._until.get(key_id, 0.0) > now

    def penalize(self, key_id: str, until: float) -> None:
        with self._lock:
            self._until[key_id] = until
