import math

from google.genai import types

from ingestion.config.settings import GEMINI_EMBEDDING_MODEL, EMBEDDING_DIM
from services.inference.providers.key_pool import GeminiKeyPool, get_key_pool


def l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return list(vec)
    return [x / norm for x in vec]


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
