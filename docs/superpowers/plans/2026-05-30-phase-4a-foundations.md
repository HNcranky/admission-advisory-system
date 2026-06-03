# Phase 4a — KnowledgeQA Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the small, isolated building blocks the KnowledgeQA RAG service depends on: query-side embedding, retrieval config constants, result models, and an inference policy.

**Architecture:** Four independent leaf changes, each TDD'd in its own existing test file. No behavior wired into the chat flow yet — that is Phase 4c. Nothing here changes existing behavior; the embedder default `task_type` is preserved.

**Tech Stack:** Python, Pydantic v2, pytest, google-genai (Gemini), pgvector.

> **Commit policy for this repo:** Do NOT run `git commit`. Each task ends at a checkpoint; the user reviews and commits manually.

**Spec:** `docs/superpowers/specs/2026-05-30-phase-4-knowledge-qa-rag-agent-design.md`

---

### Task 1: Parameterize embedder `task_type` (enable query-side embedding)

**Files:**
- Modify: `ingestion/knowledge/embedder.py:41-55`
- Test: `tests/ingestion/knowledge/test_embedder.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/ingestion/knowledge/test_embedder.py` (the `_FakeClient` / `_FakeModels` helpers already exist in this file):

```python
def test_embed_passes_custom_task_type():
    client = _FakeClient()
    emb = GeminiEmbedder(client=client, dim=2)

    emb.embed(["truy vấn"], task_type="RETRIEVAL_QUERY")

    assert client.models.calls[0]["config"].task_type == "RETRIEVAL_QUERY"


def test_embed_default_task_type_unchanged():
    client = _FakeClient()
    emb = GeminiEmbedder(client=client, dim=2)

    emb.embed(["tài liệu"])

    assert client.models.calls[0]["config"].task_type == "RETRIEVAL_DOCUMENT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ingestion/knowledge/test_embedder.py::test_embed_passes_custom_task_type -v`
Expected: FAIL with `TypeError: embed() got an unexpected keyword argument 'task_type'`

- [ ] **Step 3: Write minimal implementation**

In `ingestion/knowledge/embedder.py`, change the `embed` signature and the config to thread `task_type` through:

```python
    def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            response = self._get_client().models.embed_content(
                model=self.model,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=self.dim,
                ),
            )
            for emb in response.embeddings:
                out.append(l2_normalize(list(emb.values)))
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/ingestion/knowledge/test_embedder.py -v`
Expected: PASS (all tests, including the existing `test_embed_uses_retrieval_document_task_type_and_dim`)

- [ ] **Step 5: Checkpoint (do NOT commit)**

Stage if you like (`git add ingestion/knowledge/embedder.py tests/ingestion/knowledge/test_embedder.py`) but do NOT run `git commit`. Stop here for the user to review.

---

### Task 2: Add KnowledgeQA retrieval config constants

**Files:**
- Modify: `ingestion/config/settings.py:63` (after the embedding block)
- Test: `tests/ingestion/test_knowledge_qa_settings.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/ingestion/test_knowledge_qa_settings.py`:

```python
from ingestion.config import settings


def test_knowledge_qa_top_k_default_is_5():
    assert settings.KNOWLEDGE_QA_TOP_K == 5


def test_knowledge_qa_min_score_default_is_half():
    assert settings.KNOWLEDGE_QA_MIN_SCORE == 0.5


def test_knowledge_qa_top_k_env_overridable(monkeypatch):
    import importlib

    monkeypatch.setenv("KNOWLEDGE_QA_TOP_K", "8")
    reloaded = importlib.reload(settings)
    try:
        assert reloaded.KNOWLEDGE_QA_TOP_K == 8
    finally:
        monkeypatch.delenv("KNOWLEDGE_QA_TOP_K", raising=False)
        importlib.reload(settings)  # restore defaults for other tests
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ingestion/test_knowledge_qa_settings.py -v`
Expected: FAIL with `AttributeError: module 'ingestion.config.settings' has no attribute 'KNOWLEDGE_QA_TOP_K'`

- [ ] **Step 3: Write minimal implementation**

In `ingestion/config/settings.py`, immediately after the `EMBEDDING_DIM` line (line 63), add:

```python

# --- Knowledge QA retrieval (Phase 4) ------------------------------------
# Top-K chunks pulled from pgvector before generation, and the minimum
# cosine score (score = 1 - distance) the top chunk must clear. Below it the
# QA service returns "no data" WITHOUT calling the LLM (zero-hallucination gate).
KNOWLEDGE_QA_TOP_K = int(os.getenv("KNOWLEDGE_QA_TOP_K", 5))
KNOWLEDGE_QA_MIN_SCORE = float(os.getenv("KNOWLEDGE_QA_MIN_SCORE", 0.5))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/ingestion/test_knowledge_qa_settings.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Checkpoint (do NOT commit)**

Do NOT run `git commit`. Stop here for the user to review.

---

### Task 3: Add `Citation` and `KnowledgeQAResult` models

**Files:**
- Modify: `services/knowledge/models.py:1` (import) and end of file
- Test: `tests/services/knowledge/test_models.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/services/knowledge/test_models.py`:

```python
from services.knowledge.models import Citation, KnowledgeQAResult


def test_citation_carries_source_url_and_chunk_text():
    c = Citation(source_url="https://uet/hoc-phi", chunk_text="Học phí 35 triệu")
    assert c.source_url == "https://uet/hoc-phi"
    assert c.chunk_text == "Học phí 35 triệu"


def test_knowledge_qa_result_no_data_defaults():
    r = KnowledgeQAResult(has_data=False)
    assert r.has_data is False
    assert r.answer is None
    assert r.citations == []
    assert r.confidence == 0.0


def test_knowledge_qa_result_with_answer_and_citations():
    r = KnowledgeQAResult(
        has_data=True,
        answer="Học phí khoảng 35 triệu/năm.",
        citations=[Citation(source_url="u", chunk_text="t")],
        confidence=0.91,
    )
    assert r.has_data is True
    assert r.answer.startswith("Học phí")
    assert len(r.citations) == 1
    assert r.confidence == 0.91
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/knowledge/test_models.py -k "citation or knowledge_qa_result" -v`
Expected: FAIL with `ImportError: cannot import name 'Citation' from 'services.knowledge.models'`

- [ ] **Step 3: Write minimal implementation**

In `services/knowledge/models.py`, change the import line at the top:

```python
from pydantic import BaseModel, Field
```

Then append at the end of the file:

```python


class Citation(BaseModel):
    source_url: str
    chunk_text: str


class KnowledgeQAResult(BaseModel):
    has_data: bool
    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/knowledge/test_models.py -v`
Expected: PASS (all tests including the existing chunk/document tests)

- [ ] **Step 5: Checkpoint (do NOT commit)**

Do NOT run `git commit`. Stop here for the user to review.

---

### Task 4: Register the `knowledge_qa_agent` inference policy

**Files:**
- Modify: `services/inference/factory.py:8-31` (the `agent_overrides` dict)
- Test: `tests/services/inference/test_factory.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/services/inference/test_factory.py`:

```python
def test_knowledge_qa_agent_policy_uses_flash_with_json_and_fallback():
    gateway = build_default_gateway()

    policy = gateway.registry.resolve("knowledge_qa_agent")

    assert policy.primary_model == "gemini-2.5-flash"
    assert policy.output_mode == "json"
    assert policy.allow_fallback is True
    assert policy.fallback_model == "gemini-2.5-flash-lite"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/inference/test_factory.py::test_knowledge_qa_agent_policy_uses_flash_with_json_and_fallback -v`
Expected: FAIL — `policy.primary_model` resolves to the default `"gemini-2.5-flash-lite"`, not `"gemini-2.5-flash"`

- [ ] **Step 3: Write minimal implementation**

In `services/inference/factory.py`, add a new entry to the `agent_overrides` dict (after the `explanation_agent` line):

```python
            "explanation_agent": {"output_mode": "free_text", "max_retries": 1},
            "knowledge_qa_agent": {
                "primary_model": "gemini-2.5-flash",
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash-lite",
            },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/inference/test_factory.py -v`
Expected: PASS (both the existing and new test)

- [ ] **Step 5: Checkpoint (do NOT commit)**

Do NOT run `git commit`. Stop here for the user to review.

---

## Phase 4a Done — Verification

Run the whole touched surface:

```
python -m pytest tests/ingestion/knowledge/test_embedder.py tests/ingestion/test_knowledge_qa_settings.py tests/services/knowledge/test_models.py tests/services/inference/test_factory.py -v
```

Expected: all PASS. Phase 4b (`KnowledgeQAService`) depends on every symbol added here.
