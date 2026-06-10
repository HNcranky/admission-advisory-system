# Slice 03: Ngân sách token per agent trong factory

> Part of **Sprint 1 — LLM efficiency**. Spec: `docs/superpowers/specs/2026-06-10-sprint1-llm-efficiency-design.md`
> REQUIRED SUB-SKILL: superpowers:subagent-driven-development / superpowers:executing-plans. Slice này = một commit. **Phụ thuộc: 01.**

**Goal:** Đặt ngân sách output token cho các agent chính trong `agent_overrides` (nguồn cấu hình duy nhất). Agent không cấu hình giữ `None` (không giới hạn).

**Files:**
- Modify: `services/inference/factory.py` (dict `agent_overrides`)
- Test: `tests/services/inference/test_factory_budgets.py` (mới)

Ngân sách: `knowledge_qa_agent`=800, `synthesis_agent`=1200, `resolution_agent`=256, `intent_router`=256 (entry mới), `profile_extractor`=300 (entry mới).

---

- [ ] **Step 1: Write the failing test**

Create `tests/services/inference/test_factory_budgets.py`:

```python
from services.inference.factory import build_default_gateway


def test_agent_token_budgets_are_set():
    registry = build_default_gateway().registry
    assert registry.resolve("knowledge_qa_agent").max_tokens == 800
    assert registry.resolve("synthesis_agent").max_tokens == 1200
    assert registry.resolve("resolution_agent").max_tokens == 256
    assert registry.resolve("intent_router").max_tokens == 256
    assert registry.resolve("profile_extractor").max_tokens == 300


def test_unbudgeted_agent_stays_none():
    registry = build_default_gateway().registry
    assert registry.resolve("explanation_agent").max_tokens is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/inference/test_factory_budgets.py -v`
Expected: FAIL — các agent chưa có `max_tokens` (None).

- [ ] **Step 3: Write minimal implementation**

`services/inference/factory.py` — thêm `"max_tokens"` vào 3 entry sẵn có và thêm 2 entry mới (giữ nguyên các entry khác):

```python
            "resolution_agent": {
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash",
                "max_tokens": 256,
            },
            "knowledge_qa_agent": {
                "primary_model": "gemini-2.5-flash",
                "output_mode": "json",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash-lite",
                "max_tokens": 800,
            },
            "synthesis_agent": {
                "primary_model": "gemini-2.5-flash",
                "output_mode": "free_text",
                "max_retries": 1,
                "allow_fallback": True,
                "fallback_model": "gemini-2.5-flash-lite",
                "max_tokens": 1200,
            },
            "intent_router": {"output_mode": "json", "max_retries": 1, "max_tokens": 256},
            "profile_extractor": {"output_mode": "json", "max_retries": 1, "max_tokens": 300},
```

Đặt 2 entry mới (`intent_router`, `profile_extractor`) ngay sau `knowledge_classify`, trước `}` đóng `agent_overrides`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/inference/test_factory_budgets.py -v`
Expected: PASS.

- [ ] **Step 5: Regression inference suite**

Run: `python -m pytest tests/services/inference -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/inference/factory.py tests/services/inference/test_factory_budgets.py
git commit -m "feat(inference): set per-agent output token budgets"
```
