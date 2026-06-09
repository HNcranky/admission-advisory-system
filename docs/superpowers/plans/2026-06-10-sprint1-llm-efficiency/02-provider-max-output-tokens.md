# Slice 02: Provider truyền `max_output_tokens`

> Part of **Sprint 1 — LLM efficiency**. Spec: `docs/superpowers/specs/2026-06-10-sprint1-llm-efficiency-design.md`
> REQUIRED SUB-SKILL: superpowers:subagent-driven-development / superpowers:executing-plans. Slice này = một commit. **Phụ thuộc: 01.**

**Goal:** `GeminiProvider._call` truyền `max_output_tokens=policy.max_tokens` vào `GenerateContentConfig`. `None` ⇒ không giới hạn (hành vi cũ).

**Files:**
- Modify: `services/inference/providers/gemini_provider.py` (staticmethod `_call`)
- Test: `tests/services/inference/test_gemini_provider.py`

---

- [ ] **Step 1: Write the failing test**

Thêm vào cuối `tests/services/inference/test_gemini_provider.py` (helper `_pool`, `_request`, `_policy`, `FakeClient` đã có sẵn trong file):

```python
def test_max_tokens_passed_to_config_when_set():
    captured = {}
    pool = _pool({"k1": FakeClient(text='{"ok": true}', captured=captured)})
    provider = GeminiProvider(pool=pool)
    policy = InferencePolicy(agent_name="a", primary_model="m", max_tokens=321)
    provider.generate(_request(), policy)
    assert captured["config"].max_output_tokens == 321


def test_max_tokens_none_leaves_config_unbounded():
    captured = {}
    pool = _pool({"k1": FakeClient(text='{"ok": true}', captured=captured)})
    provider = GeminiProvider(pool=pool)
    provider.generate(_request(), _policy())  # _policy() → max_tokens None
    assert captured["config"].max_output_tokens is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/inference/test_gemini_provider.py::test_max_tokens_passed_to_config_when_set -v`
Expected: FAIL — `max_output_tokens` đang là `None` (provider chưa truyền).

- [ ] **Step 3: Write minimal implementation**

`services/inference/providers/gemini_provider.py` — cập nhật block `config=` trong `_call`:

```python
        return client.models.generate_content(
            model=policy.primary_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=request.system_prompt,
                temperature=request.temperature,
                response_mime_type="application/json" if json_mode else None,
                max_output_tokens=policy.max_tokens,
            ),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/inference/test_gemini_provider.py -v`
Expected: PASS — 2 test mới + mọi test cũ (regression xanh).

- [ ] **Step 5: Commit**

```bash
git add services/inference/providers/gemini_provider.py tests/services/inference/test_gemini_provider.py
git commit -m "feat(inference): pass max_output_tokens from policy to Gemini call"
```
