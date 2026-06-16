# Slice 3a — Register Sweep (bot = mình, user = bạn) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite every user-facing string where the bot addresses the user as
"em" to use "bạn", and add a guard test so "em" cannot creep back.

**Architecture:** Pure string edits in `services/explanation_service.py`,
`services/chat/conversation_service.py:241`, and the greeting title in
`web/static/js/modules/messages.js`. A new AST-based audit test scans the chat /
advisory modules' string literals (excluding comments and docstrings) and fails
if any contains the standalone token "em"/"Em". `REASON_TRANSLATIONS` and the
greeting **chips** (student's own voice) are intentionally out of scope.

**Tech Stack:** Python, pytest, `ast` module.

**Spec:** `docs/superpowers/specs/2026-06-10-slice3-naturalness-voice-design.md` §3a

**Exhaustive "em" inventory (verified 2026-06-10):**
- `explanation_service.py` lines 59, 116, 139, 183, 187, 201, 202, 223, 233.
- `conversation_service.py` line 241 (lines 35 & 110 are comments — out of scope).
- `messages.js` greeting title only (chips keep "em").

---

### Task 1: Add the register-audit guard test (failing first)

**Files:**
- Create: `tests/services/test_register_audit.py`

- [ ] **Step 1: Write the failing audit test**

```python
import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Modules that emit bot→user strings. The bot must address the user as "bạn".
MODULES = [
    "services/explanation_service.py",
    "services/chat/conversation_service.py",
    "services/chat/conversational_handler.py",
    "services/chat/knowledge_fanout.py",
    "services/profile/slots.py",
]

# Standalone "em"/"Em" token; \b handles the surrounding spaces/punctuation.
# Words like "xem", "thêm", "kèm" do NOT match (the "em" is not word-bounded).
_EM = re.compile(r"\b[Ee]m\b")


def _docstring_node_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _string_literals(rel_path):
    tree = ast.parse((ROOT / rel_path).read_text(encoding="utf-8"))
    skip = _docstring_node_ids(tree)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in skip
        ):
            yield node.value


@pytest.mark.parametrize("module", MODULES)
def test_no_user_facing_string_addresses_user_as_em(module):
    offenders = [s for s in _string_literals(module) if _EM.search(s)]
    assert not offenders, f"{module} addresses user as 'em': {offenders}"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/python -m pytest tests/services/test_register_audit.py -q`
Expected: FAIL — `explanation_service.py` and `conversation_service.py` report
offenders (the inventory above).

- [ ] **Step 3: Commit the failing guard**

```bash
git add tests/services/test_register_audit.py
git commit -m "test(chat): add register-audit guard (bot must address user as bạn)"
```

---

### Task 2: Rewrite the "em" strings in explanation_service.py

**Files:**
- Modify: `services/explanation_service.py` (lines 59, 116, 139, 183, 187, 201, 202, 223, 233)

- [ ] **Step 1: Rewrite `CLOSING_QUESTION` (l.58–61)**

Replace:

```python
CLOSING_QUESTION = (
    "Em có muốn ưu tiên theo tiêu chí nào hơn: **khả năng trúng tuyển**, "
    "**đúng sở thích**, hay **học phí an toàn nhất**?"
)
```

with:

```python
CLOSING_QUESTION = (
    "Bạn có muốn ưu tiên theo tiêu chí nào hơn: **khả năng trúng tuyển**, "
    "**đúng sở thích**, hay **học phí an toàn nhất**?"
)
```

- [ ] **Step 2: Rewrite `_correction_sentence` (l.116)**

Replace `f"Mình đã cập nhật {label} của em từ {_fmt_num(prev)} {direction} {_fmt_num(new)}. "`
with `f"Mình đã cập nhật {label} của bạn từ {_fmt_num(prev)} {direction} {_fmt_num(new)}. "`

- [ ] **Step 3: Rewrite `_intro_paragraph` (l.139)**

Replace `f"Dựa trên hồ sơ hiện tại của em — {', '.join(facts)} — "`
with `f"Dựa trên hồ sơ hiện tại của bạn — {', '.join(facts)} — "`

- [ ] **Step 4: Rewrite `_no_match_block` (l.183, 187, 201, 202)**

- l.183: `majors = ", ".join(profile.preferred_majors[:3]) or "em quan tâm"`
  → `majors = ", ".join(profile.preferred_majors[:3]) or "bạn quan tâm"`
- l.187: `f"{profile.subject_combination}; em có thể cân nhắc tổ hợp khác hoặc ngành gần."`
  → `f"{profile.subject_combination}; bạn có thể cân nhắc tổ hợp khác hoặc ngành gần."`
- l.201: `"Em có thể cân nhắc: " + "; ".join(suggestions)`
  → `"Bạn có thể cân nhắc: " + "; ".join(suggestions)`
- l.202: `+ ". Mình sẽ không tự nới tiêu chí khi chưa có xác nhận của em."`
  → `+ ". Mình sẽ không tự nới tiêu chí khi chưa có xác nhận của bạn."`

- [ ] **Step 5: Rewrite `_data_note` (l.223, 233)**

- l.223: `f"{label_for_source(chosen.source_url)}, nhưng em nên kiểm tra thông báo "`
  → `f"{label_for_source(chosen.source_url)}, nhưng bạn nên kiểm tra thông báo "`
- l.233: `"Em nên kiểm tra trực tiếp với trường trước khi đăng ký."`
  → `"Bạn nên kiểm tra trực tiếp với trường trước khi đăng ký."`

- [ ] **Step 6: Update the two existing tests that assert the old closing wording**

In `tests/agents/test_explanation_agent.py`:
- Line ~260: `assert "Em có muốn ưu tiên theo tiêu chí nào hơn" in output.final_answer`
  → `assert "Bạn có muốn ưu tiên theo tiêu chí nào hơn" in output.final_answer`
- Line ~415: `assert "Em có muốn ưu tiên theo tiêu chí nào hơn" not in answer`
  → `assert "Bạn có muốn ưu tiên theo tiêu chí nào hơn" not in answer`

- [ ] **Step 7: Run the explanation tests**

Run: `.venv/bin/python -m pytest tests/agents/test_explanation_agent.py -q`
Expected: PASS (all advisory wording assertions hold with "bạn").

---

### Task 3: Rewrite the ack string in conversation_service.py

**Files:**
- Modify: `services/chat/conversation_service.py:241`

- [ ] **Step 1: Rewrite the correction ack**

Replace `ack = "Mình sẽ tính lại với thông tin em vừa cập nhật."`
with `ack = "Mình sẽ tính lại với thông tin bạn vừa cập nhật."`

- [ ] **Step 2: Run conversation-service tests**

Run: `.venv/bin/python -m pytest tests/services/chat/test_conversation_service.py -q`
Expected: PASS.

---

### Task 4: Rewrite the greeting title in messages.js

**Files:**
- Modify: `web/static/js/modules/messages.js` (the `transcript-greeting__title` line)

- [ ] **Step 1: Rewrite the bot's greeting title**

Replace `Xin chào! Hãy mô tả tình hình xét tuyển của em...`
with `Xin chào! Hãy mô tả tình hình xét tuyển của bạn...`
(Leave the `GREETING_PROMPTS` chips unchanged — they are the student's own voice.)

---

### Task 5: Run the guard + full suite, commit

- [ ] **Step 1: Run the register-audit guard (now green)**

Run: `.venv/bin/python -m pytest tests/services/test_register_audit.py -q`
Expected: PASS — no module reports "em" offenders.

- [ ] **Step 2: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add services/explanation_service.py services/chat/conversation_service.py \
        web/static/js/modules/messages.js tests/agents/test_explanation_agent.py
git commit -m "feat(chat): unify advisory/chat register to bot=mình, user=bạn"
```
