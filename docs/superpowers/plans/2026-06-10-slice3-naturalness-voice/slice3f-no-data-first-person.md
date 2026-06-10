# Slice 3f — First-Person "No Data" Fallbacks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cold "Hệ thống chưa có dữ liệu…" no-data fallbacks with a
warmer first-person "Mình hiện chưa có…" in the mình/bạn register.

**Architecture:** Two string edits — `services/chat/knowledge_fanout.py:111`
(`format_knowledge_blocks` fallback) and
`services/chat/conversation_service.py:347` (the knowledge-QA no-data body). A
behavioral test on `format_knowledge_blocks` plus a source-scan guard asserting
neither module still contains "Hệ thống chưa có".

**Tech Stack:** Python, pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-slice3-naturalness-voice-design.md` §3f

**Note:** the empathy-first emotional-support reply and the conversational-
handler register are **already** implemented; this plan only touches the two
remaining cold no-data strings.

---

### Task 1: First-person fanout fallback

**Files:**
- Modify: `services/chat/knowledge_fanout.py:111`
- Test: `tests/services/chat/test_knowledge_fanout.py`

- [ ] **Step 1: Write the failing behavioral test**

Append to `tests/services/chat/test_knowledge_fanout.py`:

```python
def test_format_knowledge_blocks_no_data_uses_first_person():
    from services.chat.knowledge_fanout import format_knowledge_blocks
    from services.chat.hybrid_models import KnowledgeBlock

    blocks = [KnowledgeBlock(school="hust", topic="tuition", has_data=False)]
    text = format_knowledge_blocks(blocks)

    assert "Hệ thống chưa có" not in text
    assert text.startswith("Mình hiện chưa có dữ liệu")
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/python -m pytest tests/services/chat/test_knowledge_fanout.py::test_format_knowledge_blocks_no_data_uses_first_person -q`
Expected: FAIL — current text starts with "Hệ thống chưa có dữ liệu cho thông tin bạn hỏi."

- [ ] **Step 3: Rewrite the fallback (l.109–113)**

Replace:

```python
        return (
            "Hệ thống chưa có dữ liệu cho thông tin bạn hỏi. "
            "Bạn có thể liên hệ trực tiếp nhà trường để biết thêm chi tiết."
        )
```

with:

```python
        return (
            "Mình hiện chưa có dữ liệu cho thông tin bạn hỏi. "
            "Bạn có thể liên hệ trực tiếp nhà trường để biết thêm chi tiết."
        )
```

- [ ] **Step 4: Run to confirm it passes**

Run: `.venv/bin/python -m pytest tests/services/chat/test_knowledge_fanout.py -q`
Expected: PASS.

---

### Task 2: First-person knowledge-QA no-data body

**Files:**
- Modify: `services/chat/conversation_service.py:347`

- [ ] **Step 1: Rewrite the no-data body**

In `services/chat/conversation_service.py` (the `else` branch around l.346–349),
replace:

```python
                f"Hệ thống chưa có dữ liệu về {topic_label} của {school_label}. "
```

with:

```python
                f"Mình hiện chưa có dữ liệu về {topic_label} của {school_label}. "
```

---

### Task 3: Source-scan guard + full suite, commit

**Files:**
- Test: `tests/services/chat/test_knowledge_fanout.py`

- [ ] **Step 1: Add a source-scan guard for both modules**

Append to `tests/services/chat/test_knowledge_fanout.py`:

```python
def test_no_module_uses_cold_system_phrasing():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    for rel in ["services/chat/knowledge_fanout.py", "services/chat/conversation_service.py"]:
        text = (root / rel).read_text(encoding="utf-8")
        assert "Hệ thống chưa có" not in text, f"{rel} still uses cold 'Hệ thống chưa có'"
```

- [ ] **Step 2: Run the guard + full suite**

Run: `.venv/bin/python -m pytest tests/services/chat/test_knowledge_fanout.py -q && .venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add services/chat/knowledge_fanout.py services/chat/conversation_service.py \
        tests/services/chat/test_knowledge_fanout.py
git commit -m "feat(chat): first-person 'no data' fallbacks (Mình hiện chưa có…)"
```
