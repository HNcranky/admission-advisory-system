# Slice 01: `max_tokens` trên policy + registry resolve

> Part of **Sprint 1 — LLM efficiency**. Spec: `docs/superpowers/specs/2026-06-10-sprint1-llm-efficiency-design.md`
> REQUIRED SUB-SKILL: superpowers:subagent-driven-development / superpowers:executing-plans. Slice này = một commit. Phụ thuộc: không.

**Goal:** `InferencePolicy` mang field `max_tokens` (mặc định `None`), và `ModelRegistry.resolve` đọc nó từ `agent_overrides`.

**Files:**
- Modify: `services/inference/models.py` (class `InferencePolicy`)
- Modify: `services/inference/registry.py` (method `resolve`)
- Test: `tests/services/inference/test_registry.py`

---

- [ ] **Step 1: Write the failing test**

Thêm vào cuối `tests/services/inference/test_registry.py`:

```python
from services.inference.registry import ModelRegistry


def test_resolve_reads_max_tokens_from_override():
    registry = ModelRegistry(default_model="m", agent_overrides={"a": {"max_tokens": 512}})
    assert registry.resolve("a").max_tokens == 512


def test_resolve_max_tokens_defaults_to_none():
    registry = ModelRegistry(default_model="m")
    assert registry.resolve("a").max_tokens is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/inference/test_registry.py::test_resolve_reads_max_tokens_from_override -v`
Expected: FAIL — `InferencePolicy` chưa có field `max_tokens`.

- [ ] **Step 3: Write minimal implementation**

`services/inference/models.py` — thêm field cuối class `InferencePolicy`:

```python
class InferencePolicy(BaseModel):
    agent_name: str
    primary_model: str
    fallback_model: Optional[str] = None
    allow_fallback: bool = False
    output_mode: str = "free_text"
    max_retries: int = 1
    max_tokens: Optional[int] = None
```

`services/inference/registry.py` — `resolve()`:

```python
    def resolve(self, agent_name: str) -> InferencePolicy:
        override = self.agent_overrides.get(agent_name, {})
        raw_max_tokens = override.get("max_tokens")
        return InferencePolicy(
            agent_name=agent_name,
            primary_model=str(override.get("primary_model", self.default_model)),
            fallback_model=override.get("fallback_model"),
            allow_fallback=bool(override.get("allow_fallback", False)),
            output_mode=str(override.get("output_mode", "free_text")),
            max_retries=int(override.get("max_retries", 1)),
            max_tokens=int(raw_max_tokens) if raw_max_tokens is not None else None,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/inference/test_registry.py -v`
Expected: PASS (toàn file).

- [ ] **Step 5: Commit**

```bash
git add services/inference/models.py services/inference/registry.py tests/services/inference/test_registry.py
git commit -m "feat(inference): add max_tokens to InferencePolicy + registry resolve"
```
