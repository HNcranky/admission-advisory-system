# Slice 3b — Advisory-Failure Message Diacritics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the de-accented ASCII advisory-failure message with proper
Vietnamese diacritics in the mình/bạn register.

**Architecture:** One string change in `RunDispatcher._mark_failed`
(`services/chat/run_dispatcher.py:51`). The dispatcher already has an inline-
executor test harness (`tests/services/chat/test_run_dispatcher.py`); add a test
that forces the runner to raise and asserts the new message is appended.

**Tech Stack:** Python, pytest (in-memory fakes — no DB).

**Spec:** `docs/superpowers/specs/2026-06-10-slice3-naturalness-voice-design.md` §3b

---

### Task 1: Assert the failure message has diacritics

**Files:**
- Modify: `services/chat/run_dispatcher.py:51`
- Test: `tests/services/chat/test_run_dispatcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/services/chat/test_run_dispatcher.py`:

```python
def test_dispatcher_failure_message_uses_diacritics_and_register():
    repo = FakeRepository()

    def boom(profile_state, latest_user_message, trace_run_id=None, correction_note=None):
        raise RuntimeError("inference down")

    dispatcher = RunDispatcher(repository=repo, runner=boom, executor=InlineExecutor())

    try:
        dispatcher.submit(
            session_token="session-err",
            run_id=11,
            latest_user_message="Tu van",
            profile_state=ChatProfileState(admission_year=2026),
        )
    except RuntimeError:
        pass  # _execute re-raises after recording the failure

    error_msgs = [m for m in repo.messages if m[2] == "assistant_error"]
    assert error_msgs, "expected an assistant_error message"
    text = error_msgs[-1][3]
    assert text == "Xin lỗi, quá trình phân tích bị gián đoạn. Bạn thử lại giúp mình nhé."
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `.venv/bin/python -m pytest tests/services/chat/test_run_dispatcher.py::test_dispatcher_failure_message_uses_diacritics_and_register -q`
Expected: FAIL — current message is ASCII "Xin loi, qua trinh phan tich bi gian doan. Ban hay thu lai."

- [ ] **Step 3: Rewrite the message**

In `services/chat/run_dispatcher.py:51`, replace
`"Xin loi, qua trinh phan tich bi gian doan. Ban hay thu lai."`
with
`"Xin lỗi, quá trình phân tích bị gián đoạn. Bạn thử lại giúp mình nhé."`

- [ ] **Step 4: Run the test to confirm it passes**

Run: `.venv/bin/python -m pytest tests/services/chat/test_run_dispatcher.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/chat/run_dispatcher.py tests/services/chat/test_run_dispatcher.py
git commit -m "fix(chat): proper diacritics + register on advisory-failure message"
```
