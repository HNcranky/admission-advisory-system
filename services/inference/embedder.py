import math
import threading
from collections import OrderedDict

from google.genai import types

from ingestion.config.settings import GEMINI_EMBEDDING_MODEL, EMBEDDING_DIM, EMBED_CACHE_SIZE
from services.inference.providers.key_pool import GeminiKeyPool, get_key_pool


def l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return list(vec)
    return [x / norm for x in vec]


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


class GeminiEmbedder:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        pool=None,
        client_factory=None,
        model: str = GEMINI_EMBEDDING_MODEL,
        dim: int = EMBEDDING_DIM,
        batch_size: int = 100,
    ):
        # Same key-resolution contract as GeminiProvider: explicit pool wins,
        # then a single api_key (1-key pool), else the env-backed singleton.
        # Embedding shares the pool so 429/auth/5xx rotate keys like the rest.
        if pool is not None:
            self._pool = pool
        elif api_key is not None:
            kwargs = {"client_factory": client_factory} if client_factory else {}
            self._pool = GeminiKeyPool([api_key], **kwargs)
        else:
            self._pool = get_key_pool()
        self.model = model
        self.dim = dim
        self.batch_size = batch_size

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
