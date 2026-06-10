# Slice 2c (part 1) — Retrieval-Query Helper — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pure, side-effect-free helper that builds the text to embed for
knowledge retrieval — prepending the previous user turn only for elided
follow-ups, and returning standalone questions verbatim.

**Architecture:** New module `services/knowledge/retrieval_query.py` exposing
`build_retrieval_query(question, prev_user) -> str`. String-level ellipsis
heuristic (no LLM, no IO). Wiring into call sites is a separate plan
(`slice2d-wire-retrieval-query.md`); this plan ships the helper + its unit tests
only.

**Tech Stack:** Python, pytest (pure unit tests — no DB, no network).

**Spec:** `docs/superpowers/specs/2026-06-10-slice2-rag-latency-design.md` §2c

---

### Task 1: `build_retrieval_query` helper

**Files:**
- Create: `services/knowledge/retrieval_query.py`
- Test: `tests/services/knowledge/test_retrieval_query.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/services/knowledge/test_retrieval_query.py`:

```python
from services.knowledge.retrieval_query import build_retrieval_query


def test_standalone_question_with_topic_noun_returned_verbatim():
    q = "học phí của HUST là bao nhiêu"
    assert build_retrieval_query(q, "ngành CNTT thế nào") == q


def test_continuation_cue_prepends_prev_user():
    q = "còn ngành CNTT thì sao"
    prev = "học phí HUST bao nhiêu"
    assert build_retrieval_query(q, prev) == f"{prev}\n{q}"


def test_short_question_without_noun_or_cue_prepends():
    q = "cái đó thế nào"  # short, no topic noun, no leading cue → elliptical
    prev = "HUST tuyển sinh ra sao"
    assert build_retrieval_query(q, prev) == f"{prev}\n{q}"


def test_empty_prev_user_returns_question_verbatim():
    q = "còn thì sao"
    assert build_retrieval_query(q, "") == q
    assert build_retrieval_query(q, "   ") == q


def test_long_question_not_treated_as_elliptical():
    # >8 words and contains a topic noun → self-contained, returned verbatim
    q = "cho mình hỏi mức học phí của trường đại học bách khoa năm nay là bao nhiêu"
    assert build_retrieval_query(q, "câu trước đó") == q


def test_none_inputs_do_not_crash():
    assert build_retrieval_query(None, None) == ""
```

- [ ] **Step 2: Run the tests, verify they fail**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_retrieval_query.py -v`
Expected: FAIL — `ModuleNotFoundError: services.knowledge.retrieval_query`.

- [ ] **Step 3: Implement the helper**

Create `services/knowledge/retrieval_query.py`:

```python
"""Build the text to embed for knowledge retrieval.

Pure string logic — no IO, no LLM. For an elided follow-up ("còn học phí thì
sao?") the current question alone embeds without its referent, so we prepend the
previous user turn. Standalone (self-contained) questions are returned verbatim
so their retrieval is unchanged.
"""

# Leading words that signal a follow-up referring back to the prior turn.
_LEADING_CUES = {"còn", "thế", "vậy"}
# Multi-word continuation cues that can appear anywhere in the question.
_PHRASE_CUES = ("thì sao", "so với")
# Nouns that mark a self-contained question (names its own school/topic).
_TOPIC_NOUNS = (
    "học phí", "học bổng", "ký túc xá", "chương trình", "ngành",
    "điểm chuẩn", "chỉ tiêu", "phương thức", "xét tuyển", "trường",
)
# An elliptical question is short; long ones usually carry their own context.
_MAX_ELLIPTICAL_WORDS = 8


def _is_elliptical(question: str) -> bool:
    q = question.strip().lower()
    if not q:
        return False
    words = q.split()
    if len(words) > _MAX_ELLIPTICAL_WORDS:
        return False
    if words[0] in _LEADING_CUES or any(p in q for p in _PHRASE_CUES):
        return True
    if not any(noun in q for noun in _TOPIC_NOUNS):
        return True
    return False


def build_retrieval_query(question: str, prev_user: str) -> str:
    """Text to embed for retrieval.

    Prepends the previous user turn only when (a) there is a previous turn and
    (b) the question looks elliptical; otherwise returns the question verbatim so
    standalone retrieval is byte-for-byte unchanged.
    """
    question = question or ""
    prev_user = (prev_user or "").strip()
    if not prev_user:
        return question
    if not _is_elliptical(question):
        return question
    return f"{prev_user}\n{question}"
```

- [ ] **Step 4: Run the tests, verify they pass**

Run: `.venv/bin/python -m pytest tests/services/knowledge/test_retrieval_query.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add services/knowledge/retrieval_query.py tests/services/knowledge/test_retrieval_query.py
git commit -m "feat(knowledge): add build_retrieval_query helper for elided follow-ups"
```

---

**Tuning note for the executor:** the heuristic deliberately starts strict
(leading cue / phrase cue / no-noun, all gated on ≤8 words). If a real follow-up
fixture is missed in `slice2d`, loosen `_TOPIC_NOUNS` or `_MAX_ELLIPTICAL_WORDS`
here and add a regression test — do not reach for an LLM rewrite (explicitly out
of scope in the spec).
