import math
from types import SimpleNamespace

import pytest

from ingestion.knowledge.embedder import GeminiEmbedder, l2_normalize
from services.inference.providers import key_pool as key_pool_module
from services.inference.providers.key_pool import GeminiKeyPool, reset_key_pool


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_key_pool()
    yield
    reset_key_pool()


# --- l2_normalize -------------------------------------------------------------

def test_l2_normalize_unit_length():
    out = l2_normalize([3.0, 4.0])
    assert math.isclose(math.sqrt(sum(x * x for x in out)), 1.0, rel_tol=1e-9)
    assert math.isclose(out[0], 0.6, rel_tol=1e-9)
    assert math.isclose(out[1], 0.8, rel_tol=1e-9)


def test_l2_normalize_zero_vector_returned_unchanged():
    assert l2_normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]


# --- test doubles -------------------------------------------------------------

class FakeAPIError(Exception):
    """Mimics google.genai APIError: carries an int `code`."""

    def __init__(self, code, message=""):
        super().__init__(message or f"{code} error")
        self.code = code


class _FakeEmbedding:
    def __init__(self, values):
        self.values = values


class _FakeModels:
    def __init__(self, *, exc=None):
        self.calls = []
        self._exc = exc

    def embed_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        if self._exc is not None:
            raise self._exc
        # one raw (un-normalized) vector per input: [len(text), 0]
        return SimpleNamespace(
            embeddings=[_FakeEmbedding([float(len(t)), 0.0]) for t in contents]
        )


class _FakeClient:
    def __init__(self, *, exc=None):
        self.models = _FakeModels(exc=exc)


def _pool(client_map):
    """client_map: {key_id: _FakeClient}. Keys ordered by insertion."""
    keys = list(client_map.keys())
    return GeminiKeyPool(keys, client_factory=lambda k: client_map[k])


# --- embed --------------------------------------------------------------------

def test_embed_returns_one_normalized_vector_per_text():
    emb = GeminiEmbedder(pool=_pool({"k1": _FakeClient()}), dim=2)

    out = emb.embed(["abcd", "xy"])

    assert len(out) == 2
    for v in out:
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-9)
    assert out[0] == [1.0, 0.0]


def test_embed_uses_retrieval_document_task_type_and_dim():
    client = _FakeClient()
    emb = GeminiEmbedder(pool=_pool({"k1": client}), dim=2)

    emb.embed(["one"])

    call = client.models.calls[0]
    assert call["config"].task_type == "RETRIEVAL_DOCUMENT"
    assert call["config"].output_dimensionality == 2


def test_embed_batches_at_batch_size():
    client = _FakeClient()
    emb = GeminiEmbedder(pool=_pool({"k1": client}), dim=2, batch_size=2)

    emb.embed(["a", "b", "c", "d", "e"])  # 5 texts, batch_size 2 → 3 calls

    assert len(client.models.calls) == 3
    assert [len(c["contents"]) for c in client.models.calls] == [2, 2, 1]


def test_embed_empty_list_makes_no_calls():
    client = _FakeClient()
    emb = GeminiEmbedder(pool=_pool({"k1": client}), dim=2)
    assert emb.embed([]) == []
    assert client.models.calls == []


def test_embed_passes_custom_task_type():
    client = _FakeClient()
    emb = GeminiEmbedder(pool=_pool({"k1": client}), dim=2)

    emb.embed(["truy vấn"], task_type="RETRIEVAL_QUERY")

    assert client.models.calls[0]["config"].task_type == "RETRIEVAL_QUERY"


def test_embed_default_task_type_unchanged():
    client = _FakeClient()
    emb = GeminiEmbedder(pool=_pool({"k1": client}), dim=2)

    emb.embed(["tài liệu"])

    assert client.models.calls[0]["config"].task_type == "RETRIEVAL_DOCUMENT"


# --- key rotation (the whole point of unifying on GeminiKeyPool) --------------

def test_embed_rotates_to_next_key_on_429():
    """A 429 on a batch cools the key down and retries the batch on the next key."""
    pool = _pool({
        "k1": _FakeClient(exc=FakeAPIError(429, "quota")),
        "k2": _FakeClient(),
    })
    emb = GeminiEmbedder(pool=pool, dim=2)

    out = emb.embed(["abcd"])

    assert out == [[1.0, 0.0]]
    assert pool.acquire().key_id == "k2"  # k1 penalized → skipped


def test_embed_raises_when_all_keys_rate_limited():
    from services.inference.models import InferenceError

    pool = _pool({
        "k1": _FakeClient(exc=FakeAPIError(429)),
        "k2": _FakeClient(exc=FakeAPIError(429)),
    })
    emb = GeminiEmbedder(pool=pool, dim=2)

    with pytest.raises(InferenceError, match="exhausted or cooling down"):
        emb.embed(["x"])


# --- construction -------------------------------------------------------------

def test_api_key_constructor_builds_single_key_pool():
    client = _FakeClient()
    emb = GeminiEmbedder(api_key="legacy-key", client_factory=lambda k: client, dim=2)

    out = emb.embed(["ab"])

    assert out == [[1.0, 0.0]]
    assert client.models.calls[0]["config"].output_dimensionality == 2


def test_default_constructor_uses_env_singleton(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    reset_key_pool()
    emb = GeminiEmbedder()
    # no keys configured → empty pool, no embedding attempted
    assert emb.embed([]) == []
