# Slice 3d — Band-Aware Intro + Rotating Closing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the advisory intro react to the top recommendation's score band,
rotate the closing question across advisories, and skip the closing entirely on a
correction/follow-up re-run.

**Architecture:** `explanation_service.py` gets a `CLOSING_VARIANTS` list and a
`closing_seed: int` parameter on `build_explanation`; the closing is skipped when
`correction_note` is set and otherwise picked by `closing_seed % len`. The intro
gains a band-aware lead clause. A per-session advisory ordinal is threaded
`chat_api → RunDispatcher → run_advisory_for_session → AgentState.closing_seed →
explanation_agent → build_explanation`. A new `ChatSessionRepository.count_runs`
supplies the ordinal.

**Tech Stack:** Python, pytest (fakes for dispatcher/repository — no DB).

**Spec:** `docs/superpowers/specs/2026-06-10-slice3-naturalness-voice-design.md` §3d

**Depends on:** slice 3a (it converted `CLOSING_QUESTION` to "Bạn có muốn…");
`CLOSING_VARIANTS[0]` keeps that exact string so seed 0 is unchanged.

---

### Task 1: Band-aware intro + rotating/skipping closing in explanation_service

**Files:**
- Modify: `services/explanation_service.py`
- Test: `tests/agents/test_explanation_agent.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/agents/test_explanation_agent.py`:

```python
from services.explanation_service import build_explanation, CLOSING_VARIANTS


def _one_rec(band="safe"):
    profile = StudentProfile(total_score=27.0, subject_combination="A00",
                             preferred_majors=["computer_science"])
    candidate = CandidateProgram(
        candidate_id="hust:1", school_id="hust", school_name="HUST",
        admission_year=2026, program_id="computer_science",
        program_name="Khoa hoc May tinh", admission_method="thpt_score",
    )
    rec = RankedRecommendation(candidate_id="hust:1", band=band, score=0.9, summary="fit")
    return profile, [rec], [candidate]


def test_closing_rotates_by_seed():
    profile, recs, cands = _one_rec()
    out0 = build_explanation(profile, recs, cands, None, closing_seed=0)
    out1 = build_explanation(profile, recs, cands, None, closing_seed=1)
    assert out0.endswith(CLOSING_VARIANTS[0])
    assert out1.endswith(CLOSING_VARIANTS[1])
    assert CLOSING_VARIANTS[0] != CLOSING_VARIANTS[1]


def test_no_closing_on_correction_rerun():
    profile, recs, cands = _one_rec()
    out = build_explanation(
        profile, recs, cands, None,
        correction_note={"slot": "total_score", "previous_value": 27.0, "new_value": 25.0},
        closing_seed=0,
    )
    for variant in CLOSING_VARIANTS:
        assert variant not in out


def test_intro_lead_differs_by_band():
    profile, recs_safe, cands = _one_rec(band="safe")
    profile2, recs_reach, cands2 = _one_rec(band="reach")
    safe_out = build_explanation(profile, recs_safe, cands, None)
    reach_out = build_explanation(profile2, recs_reach, cands2, None)
    assert "Hồ sơ của bạn đang khá cạnh tranh." in safe_out
    assert "Có một vài lựa chọn bạn nên cân nhắc kỹ." in reach_out
```

- [ ] **Step 2: Run to confirm it fails**

Run: `.venv/bin/python -m pytest tests/agents/test_explanation_agent.py -k "rotates or correction_rerun or intro_lead" -q`
Expected: FAIL — `CLOSING_VARIANTS` undefined; `build_explanation` has no
`closing_seed`.

- [ ] **Step 3: Replace `CLOSING_QUESTION` with `CLOSING_VARIANTS` + intro lead constants**

In `services/explanation_service.py`, replace the `CLOSING_QUESTION` constant
(l.58–61) with:

```python
CLOSING_VARIANTS = [
    # [0] giữ nguyên chuỗi slice 3a để seed 0 không đổi hành vi.
    "Bạn có muốn ưu tiên theo tiêu chí nào hơn: **khả năng trúng tuyển**, "
    "**đúng sở thích**, hay **học phí an toàn nhất**?",
    "Giữa **khả năng trúng tuyển**, **đúng sở thích** và **học phí an toàn nhất**, "
    "bạn muốn mình ưu tiên tiêu chí nào?",
    "Bạn muốn mình sắp xếp ưu tiên theo **khả năng trúng tuyển**, **đúng sở thích** "
    "hay **học phí an toàn nhất**?",
]

# Câu dẫn mở đầu theo band của đề xuất tốt nhất (3d). Mặc định cho reach/unknown.
_BAND_INTRO_LEAD = {
    "safe": "Hồ sơ của bạn đang khá cạnh tranh.",
    "match": "Hồ sơ của bạn có một số lựa chọn phù hợp.",
}
_DEFAULT_INTRO_LEAD = "Có một vài lựa chọn bạn nên cân nhắc kỹ."
```

- [ ] **Step 4: Add a band-aware lead to `_intro_paragraph`**

Change the signature and prepend the lead. Replace the `_intro_paragraph`
definition header (l.121):

```python
def _intro_paragraph(profile: StudentProfile, admission_year: Optional[int], n: int) -> str:
```

with:

```python
def _intro_paragraph(profile: StudentProfile, admission_year: Optional[int], n: int,
                     top_band: Optional[str] = None) -> str:
    lead = _BAND_INTRO_LEAD.get(top_band, _DEFAULT_INTRO_LEAD)
```

Then prepend `lead + " "` to **both** return strings of the function. Replace:

```python
    if facts:
        return (
            f"Dựa trên hồ sơ hiện tại của bạn — {', '.join(facts)} — "
            f"mình đề xuất {n} lựa chọn sau:"
        )
    return f"Dựa trên thông tin hiện có, mình đề xuất {n} lựa chọn sau:"
```

with:

```python
    if facts:
        return (
            f"{lead} Dựa trên hồ sơ hiện tại của bạn — {', '.join(facts)} — "
            f"mình đề xuất {n} lựa chọn sau:"
        )
    return f"{lead} Dựa trên thông tin hiện có, mình đề xuất {n} lựa chọn sau:"
```

- [ ] **Step 5: Thread `closing_seed` + `top_band` through `build_explanation`**

Add the parameter to the signature (after `eligibility_checks`, l.262–271):

```python
    eligibility_checks: Optional[List[EligibilityCheck]] = None,
    closing_seed: int = 0,
) -> str:
```

Pass the top band into the intro call (l.300). Replace:

```python
        lines.append(_intro_paragraph(profile, admission_year, len(renderable)))
```

with:

```python
        top_band = renderable[0][0].band
        lines.append(_intro_paragraph(profile, admission_year, len(renderable), top_band))
```

Replace the closing block (l.374–376):

```python
    if renderable:
        lines.append("")
        lines.append(CLOSING_QUESTION)
```

with:

```python
    if renderable and not correction_note:
        lines.append("")
        lines.append(CLOSING_VARIANTS[closing_seed % len(CLOSING_VARIANTS)])
```

- [ ] **Step 6: Run the explanation tests**

Run: `.venv/bin/python -m pytest tests/agents/test_explanation_agent.py -q`
Expected: PASS. (Existing tests still hold: `CLOSING_VARIANTS[0]` is the 3a
string; the intro lead only prepends to the line that already carries the
fact list.)

- [ ] **Step 7: Commit**

```bash
git add services/explanation_service.py tests/agents/test_explanation_agent.py
git commit -m "feat(advisory): band-aware intro + rotating/skip-on-correction closing"
```

---

### Task 2: Thread `closing_seed` through state → agent → runner → dispatcher

**Files:**
- Modify: `state.py` (AgentState), `agents/explanation_agent.py`,
  `services/chat/advisory_runner.py`, `services/chat/run_dispatcher.py`
- Test: `tests/services/chat/test_run_dispatcher.py`

- [ ] **Step 1: Add `closing_seed` to `AgentState`**

In `state.py`, next to `correction_note` (l.49), add:

```python
    closing_seed: int = 0
```

- [ ] **Step 2: Pass it from the explanation agent**

In `agents/explanation_agent.py`, add to the `build_explanation(...)` call
(after `eligibility_checks=...`):

```python
        closing_seed=state.closing_seed,
```

- [ ] **Step 3: Accept it in the runner and seed the state**

In `services/chat/advisory_runner.py`, change the signature:

```python
def run_advisory_for_session(profile_state, latest_user_message: str, trace_run_id: int | None = None,
                             correction_note: dict | None = None, closing_seed: int = 0):
```

and add `closing_seed=closing_seed,` to the `AgentState(...)` constructor
(after `correction_note=correction_note,`).

- [ ] **Step 4: Forward it through the dispatcher**

In `services/chat/run_dispatcher.py`, add `closing_seed: int = 0` to both
`submit` and `_execute` signatures, forward it in the `self.executor.submit(...)`
call, and pass it to the runner. The `_execute` runner call becomes:

```python
            result = self.runner(profile_state, latest_user_message, trace_run_id=run_id,
                                 correction_note=correction_note, closing_seed=closing_seed)
```

- [ ] **Step 5: Update the dispatcher test runner fakes**

In `tests/services/chat/test_run_dispatcher.py`, every runner callable must
accept the new kwarg. Add `closing_seed=None` to each runner lambda/function
signature (the three lambdas at the `runner=` arguments and the `boom`/`runner`
helpers). Also add a focused test:

```python
def test_dispatcher_forwards_closing_seed_to_runner():
    repo = FakeRepository()
    captured = {}

    def runner(profile_state, latest_user_message, trace_run_id=None,
               correction_note=None, closing_seed=None):
        captured["closing_seed"] = closing_seed
        return {"final_answer": "ok"}

    dispatcher = RunDispatcher(repository=repo, runner=runner, executor=InlineExecutor())
    dispatcher.submit(
        session_token="s", run_id=1, latest_user_message="hi",
        profile_state=ChatProfileState(admission_year=2026), closing_seed=3,
    )
    assert captured["closing_seed"] == 3
```

- [ ] **Step 6: Run the dispatcher tests**

Run: `.venv/bin/python -m pytest tests/services/chat/test_run_dispatcher.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add state.py agents/explanation_agent.py services/chat/advisory_runner.py \
        services/chat/run_dispatcher.py tests/services/chat/test_run_dispatcher.py
git commit -m "feat(chat): thread closing_seed from dispatcher to build_explanation"
```

---

### Task 3: `count_runs` + wire the per-session ordinal in chat_api

**Files:**
- Modify: `services/chat/repository.py`, `web/routes/chat_api.py`
- Test: `tests/services/chat/test_repository_count_runs.py`

- [ ] **Step 1: Write the failing repository test (fake connection factory)**

Create `tests/services/chat/test_repository_count_runs.py`:

```python
from services.chat.repository import ChatSessionRepository


class _FakeCursor:
    def __init__(self, row):
        self._row = row
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._row

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur

    def cursor(self):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_count_runs_returns_scalar_for_session():
    cur = _FakeCursor((3,))
    repo = ChatSessionRepository(connection_factory=lambda: _FakeConn(cur))
    assert repo.count_runs("tok-123") == 3
    sql, params = cur.executed[-1]
    assert "chat_advisory_runs" in sql
    assert params == ("tok-123",)
```

- [ ] **Step 2: Run to confirm it fails**

Run: `.venv/bin/python -m pytest tests/services/chat/test_repository_count_runs.py -q`
Expected: FAIL — `count_runs` not defined.

- [ ] **Step 3: Implement `count_runs`**

Add to `services/chat/repository.py` (next to the other run methods):

```python
    def count_runs(self, session_token: str) -> int:
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM chat_advisory_runs r
                JOIN chat_sessions s ON r.session_id = s.id
                WHERE s.session_token = %s
                """,
                (session_token,),
            )
            return cur.fetchone()[0]
```

- [ ] **Step 4: Run to confirm it passes**

Run: `.venv/bin/python -m pytest tests/services/chat/test_repository_count_runs.py -q`
Expected: PASS.

- [ ] **Step 5: Wire the ordinal into chat_api**

In `web/routes/chat_api.py`, in the non-hybrid `else` branch (the
`get_run_dispatcher().submit(...)` call around l.65–71), compute the ordinal from
the just-created run and pass it. After `run_id = repo.create_run(...)` (l.54),
the current run is already counted, so the 0-based ordinal is `count - 1`:

```python
        run_id = repo.create_run(session_token, result.profile_state)
        closing_seed = max(0, repo.count_runs(session_token) - 1)
```

and add `closing_seed=closing_seed,` to the `get_run_dispatcher().submit(...)`
call.

- [ ] **Step 6: Run the full suite + commit**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

```bash
git add services/chat/repository.py web/routes/chat_api.py \
        tests/services/chat/test_repository_count_runs.py
git commit -m "feat(chat): per-session advisory ordinal feeds closing rotation seed"
```
