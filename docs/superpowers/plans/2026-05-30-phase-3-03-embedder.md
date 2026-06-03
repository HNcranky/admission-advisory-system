# Phase 3 · Plan 03 — Gemini Embedder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert a list of chunk texts into L2-normalized 768-dimension embedding vectors via Gemini, batched and fully mockable.

**Architecture:** A single `ingestion/knowledge/embedder.py` module. `GeminiEmbedder.embed(texts)` calls `client.models.embed_content` with `task_type="RETRIEVAL_DOCUMENT"` and `output_dimensionality=768`, batches at ≤100 texts/call, and L2-normalizes each vector (Gemini recommends normalization below 3072 dims). The Gemini client is injectable so unit tests pass a fake — no network, no API key.

**Tech Stack:** Python, `google-genai` (already in `requirements.txt`), pytest.

**Spec:** [`2026-05-30-phase-3-data-collection-design.md`](../specs/2026-05-30-phase-3-data-collection-design.md) §5. Settings `GEMINI_EMBEDDING_MODEL` and `EMBEDDING_DIM` already exist from Phase 2.

---

### Task 1: `l2_normalize` helper

**Files:**
- Create: `ingestion/knowledge/embedder.py`
- Test: `tests/ingestion/knowledge/test_embedder.py`

- [ ] **Step 1: Write the failing test**

`tests/ingestion/knowledge/test_embedder.py`:
```python
import math

from ingestion.knowledge.embedder import l2_normalize


def test_l2_normalize_unit_length():
    out = l2_normalize([3.0, 4.0])
    assert math.isclose(math.sqrt(sum(x * x for x in out)), 1.0, rel_tol=1e-9)
    assert math.isclose(out[0], 0.6, rel_tol=1e-9)
    assert math.isclose(out[1], 0.8, rel_tol=1e-9)


def test_l2_normalize_zero_vector_returned_unchanged():
    assert l2_normalize([0.0, 0.0, 0.0]) == [0.0, 0.0, 0.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/knowledge/test_embedder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingestion.knowledge.embedder'`.

- [ ] **Step 3: Write minimal implementation**

`ingestion/knowledge/embedder.py`:
```python
import math


def l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return list(vec)
    return [x / norm for x in vec]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingestion/knowledge/test_embedder.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/embedder.py tests/ingestion/knowledge/test_embedder.py
git commit -m "feat(knowledge): add l2_normalize helper"
```

---

### Task 2: `GeminiEmbedder.embed` with injectable client + batching

**Files:**
- Modify: `ingestion/knowledge/embedder.py`
- Test: `tests/ingestion/knowledge/test_embedder.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/ingestion/knowledge/test_embedder.py`:
```python
import math

from ingestion.knowledge.embedder import GeminiEmbedder


class _FakeEmbedding:
    def __init__(self, values):
        self.values = values


class _FakeResponse:
    def __init__(self, vectors):
        self.embeddings = [_FakeEmbedding(v) for v in vectors]


class _FakeModels:
    def __init__(self):
        self.calls = []

    def embed_content(self, *, model, contents, config):
        # Record the call, return one raw (un-normalized) vector per input.
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        return _FakeResponse([[float(len(t)), 0.0] for t in contents])


class _FakeClient:
    def __init__(self):
        self.models = _FakeModels()


def test_embed_returns_one_normalized_vector_per_text():
    client = _FakeClient()
    emb = GeminiEmbedder(client=client, dim=2)

    out = emb.embed(["abcd", "xy"])

    assert len(out) == 2
    # each vector is unit length (raw vectors were [len,0] → normalize to [1,0])
    for v in out:
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-9)
    assert out[0] == [1.0, 0.0]


def test_embed_uses_retrieval_document_task_type_and_dim():
    client = _FakeClient()
    emb = GeminiEmbedder(client=client, dim=2)

    emb.embed(["one"])

    call = client.models.calls[0]
    assert call["config"].task_type == "RETRIEVAL_DOCUMENT"
    assert call["config"].output_dimensionality == 2


def test_embed_batches_at_batch_size():
    client = _FakeClient()
    emb = GeminiEmbedder(client=client, dim=2, batch_size=2)

    emb.embed(["a", "b", "c", "d", "e"])  # 5 texts, batch_size 2 → 3 calls

    assert len(client.models.calls) == 3
    assert [len(c["contents"]) for c in client.models.calls] == [2, 2, 1]


def test_embed_empty_list_makes_no_calls():
    client = _FakeClient()
    emb = GeminiEmbedder(client=client, dim=2)
    assert emb.embed([]) == []
    assert client.models.calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/ingestion/knowledge/test_embedder.py -v`
Expected: FAIL — `ImportError: cannot import name 'GeminiEmbedder'`.

- [ ] **Step 3: Write minimal implementation**

Add to `ingestion/knowledge/embedder.py` (imports at top, class below `l2_normalize`):
```python
import os

from google import genai
from google.genai import types

from ingestion.config.settings import GEMINI_EMBEDDING_MODEL, EMBEDDING_DIM


class GeminiEmbedder:
    def __init__(
        self,
        client=None,
        api_key: str | None = None,
        model: str = GEMINI_EMBEDDING_MODEL,
        dim: int = EMBEDDING_DIM,
        batch_size: int = 100,
    ):
        self.model = model
        self.dim = dim
        self.batch_size = batch_size
        self._api_key = api_key
        self._client = client  # may be None — built lazily on first embed()

    def _get_client(self):
        # Lazy so constructing a default embedder (e.g. KnowledgePipeline's
        # default) never builds a real client / requires an API key until an
        # embed actually happens. Mirrors GeminiProvider avoiding an empty key.
        if self._client is None:
            key = self._api_key or os.getenv("GEMINI_API_KEY", "")
            self._client = genai.Client(api_key=key)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            response = self._get_client().models.embed_content(
                model=self.model,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=self.dim,
                ),
            )
            for emb in response.embeddings:
                out.append(l2_normalize(list(emb.values)))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/ingestion/knowledge/test_embedder.py -v`
Expected: PASS (6 passed).

> **Note:** `types.EmbedContentConfig` is the current `google-genai` config type. If the installed SDK version raises `AttributeError` on it, run `python -c "from google.genai import types; print([n for n in dir(types) if 'Embed' in n])"` and use the reported config class name — the call shape (model / contents / config kwargs) is unchanged.

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/embedder.py tests/ingestion/knowledge/test_embedder.py
git commit -m "feat(knowledge): add GeminiEmbedder with batching and normalization"
```

---

### Task 3: Plan-level verification

- [ ] **Step 1: Run the full plan test suite**

Run: `pytest tests/ingestion/knowledge/test_embedder.py -v`
Expected: PASS (6 passed) — entirely offline, no API key required.

## Deliverable

`GeminiEmbedder(client=...).embed(texts)` → list of L2-normalized `dim`-length vectors, batched, with the real Gemini client built only when none is injected. **Consumed by Plan 05 (pipeline)**, where a `FakeEmbedder` mirrors the same `.embed(texts)` interface.
