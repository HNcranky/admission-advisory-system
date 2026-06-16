# Plan 02 — Registry: optional `selector` field

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional `selector` field to `KnowledgeSource` so a seed entry can declare which CSS region to extract.

**Architecture:** One optional Pydantic field with default `None`. No taxonomy validation (any CSS string is allowed). Existing seeds that omit the field keep validating.

**Tech Stack:** Python, Pydantic v2, pytest.

---

### Task 1: `selector` on `KnowledgeSource`

**Files:**
- Modify: `ingestion/knowledge/registry/models.py`
- Test: `tests/ingestion/knowledge/test_registry.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/ingestion/knowledge/test_registry.py`:

```python
def test_source_accepts_optional_selector(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([
        {"school": "MOET", "source_url": "https://x",
         "document_type": "faq", "topic": "admission_policy",
         "fetch_strategy": "http", "selector": "#content"},
    ]), encoding="utf-8")
    reg = KnowledgeRegistry(seed_path=seed)
    assert reg.all_sources()[0].selector == "#content"


def test_source_selector_defaults_none(tmp_path):
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([
        {"school": "X", "source_url": "https://x",
         "document_type": "tuition_page", "topic": "tuition"},
    ]), encoding="utf-8")
    reg = KnowledgeRegistry(seed_path=seed)
    assert reg.all_sources()[0].selector is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_registry.py -k selector -v`
Expected: FAIL — `AttributeError: 'KnowledgeSource' object has no attribute 'selector'`.

- [ ] **Step 3: Add the field**

In `ingestion/knowledge/registry/models.py`, inside `class KnowledgeSource`, add the field next to the other optional fields (after `active: bool = True`):

```python
    selector: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ingestion/knowledge/test_registry.py -v`
Expected: PASS (all registry tests, including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add ingestion/knowledge/registry/models.py tests/ingestion/knowledge/test_registry.py
git commit -m "feat(knowledge): optional selector field on KnowledgeSource"
```
