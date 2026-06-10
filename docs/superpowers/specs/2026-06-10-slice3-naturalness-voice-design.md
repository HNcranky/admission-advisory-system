# Design: Slice 3 — Naturalness / Voice

**Date:** 2026-06-10
**Status:** Approved (refined after grounding review)
**Parent:** `2026-06-10-answer-quality-cost-naturalness-design.md`

## Goal

Make the assistant feel like one coherent Vietnamese advisor voice instead of
stitched-together templates: a single pronoun register, warmer
acknowledgements, varied closings, and de-duplicated caveats. This slice changes
**user-visible wording**; it must not change any *decision* (rankings,
eligibility, conflict resolution, citations).

## Locked register

- Bot refers to itself as **"mình"**; addresses the user as **"bạn"**, in every
  user-facing string the bot emits.
- The greeting sample chips in `web/static/js/modules/messages.js` are written in
  the **student's own voice** and keep **"em"** as self-reference
  (e.g. "Em muốn học ngành CNTT, điểm thi 25"). Only the bot's own lines switch
  to "bạn".

## Grounding facts (verified 2026-06-10)

The parent spec's "Now" snapshot is partly stale. Verified current state:

- **Already done** (no work needed): `services/chat/conversational_handler.py`
  already uses mình/bạn throughout, and `_EMOTIONAL_SUPPORT` (l.31–35) already
  leads with validation before any data ask. `services/profile/slots.py` prompts
  already address the user as "bạn".
- **Remaining "em" (bot addressing user)** lives in:
  - `services/explanation_service.py` — `_correction_sentence` (l.116),
    `_intro_paragraph` (l.139), `_no_match_block` (l.175/179/185/188/201–202),
    `_data_note` (l.223/233). `REASON_TRANSLATIONS` strings (l.15–29) do **not**
    address the user and stay as-is.
  - `services/chat/conversation_service.py:241` — "…thông tin em vừa cập nhật".
  - `web/static/js/modules/messages.js` greeting **title** — "…tình hình xét
    tuyển của em" (the bot's line; chips stay "em").
- **Cold no-data fallbacks** still say "Hệ thống chưa có dữ liệu":
  `services/chat/knowledge_fanout.py:111` and
  `services/chat/conversation_service.py:347`.
- `build_explanation` (`explanation_service.py:262`) already receives
  `correction_note`; it is `None` on a first advisory run and set on a
  correction/follow-up re-run (`agents/explanation_agent.py:13`,
  `state.correction_note`). This is the skip signal for the closing question.
- `build_explanation` has **no** access to a per-session run ordinal today; the
  call chain is `RunDispatcher.submit → _execute → run_advisory_for_session →
  AgentState → explanation_agent → build_explanation`
  (`services/chat/run_dispatcher.py`, `services/chat/advisory_runner.py:6`,
  `agents/explanation_agent.py:5`). A seed must be threaded through this chain.
- `_advance_advisory` (`conversation_service.py:284`) appends only the bare
  `follow_up` from `next_follow_up_question` (`slots.py:87`) with no reaction to
  the value just captured; it has `merged` (post-delta state) and the incoming
  `delta` in hand.

---

## 3a. Unify pronouns (bot=mình, user=bạn) — FIRST

- **Change:** rewrite every bot-to-user "em" → "bạn" in `explanation_service.py`
  (the functions listed above), `conversation_service.py:241`, and the
  `messages.js` greeting title. Leave `REASON_TRANSLATIONS` and the greeting
  chips untouched.
- **Acceptance:** a string-audit (grep-guard) test asserts no user-facing Python
  string in the advisory/chat layer addresses the user as "em" (the
  `messages.js` chips are user-voice and out of scope for the Python audit).
  Existing explanation/conversation tests updated to the new wording and pass.

## 3b. Fix de-accented error message

- **Now:** `services/chat/run_dispatcher.py:51` is ASCII: "Xin loi, qua trinh
  phan tich bi gian doan. Ban hay thu lai."
- **Change:** "Xin lỗi, quá trình phân tích bị gián đoạn. Bạn thử lại giúp mình
  nhé."
- **Acceptance:** the failure-path message contains correct diacritics and the
  mình/bạn register.

## 3c. Acknowledge captured slots before the next question

- **Now:** `_advance_advisory` asks one bare `follow_up` per turn with no
  reaction to the value just captured.
- **Change:** before appending the next `follow_up`:
  1. **Echo** the value(s) captured this turn (derive from `delta` vs the slot
     labels) — e.g. "Mình ghi nhận mức điểm 26."
  2. When **≥2 critical slots are now filled** (`merged`), prepend a one-line
     **recap** of what's understood and what's still needed — e.g. "Mình đã nắm:
     xét tuyển 2026, điểm 26. Còn thiếu: tổ hợp, ngành." — then the next question.
  - The echo/recap is assembled in `conversation_service.py`; the bare question
    text still comes from `slots.py`. Reuse slot display labels (mirror the
    `_SLOT_LABELS` map already in `explanation_service.py`); if a shared label
    map is convenient, factor one rather than duplicating.
  - Also **soften** the `admission_method` prompt (`slots.py:58–60`), which
    currently dumps all four methods as a bare list, into a friendlier ask.
- **Acceptance:** a fixture where a turn captures a value asserts the assistant
  message references that value before the next ask; a fixture with ≥2 filled
  slots asserts the one-line recap (filled + missing) precedes the question.

## 3d. Vary the closing question + personalize the intro

- **Now:** `explanation_service.py:58–61` `CLOSING_QUESTION` is a single constant
  appended verbatim on every advisory (`:374–376`); `_intro_paragraph`
  (`:121–142`) is a flat comma-joined fact list with no reaction to the result.
- **Change:**
  - Replace `CLOSING_QUESTION` with `CLOSING_VARIANTS` (3–4 rephrasings, all
    mình/bạn). `build_explanation` gains `closing_seed: int = 0` and picks
    `CLOSING_VARIANTS[closing_seed % len(...)]`.
  - **Skip the closing entirely when `correction_note` is set** (the user just
    answered on a re-run).
  - Seed source: thread a **per-session advisory ordinal** (0-based count of
    prior advisory runs for the session) from the dispatcher through
    `run_advisory_for_session` → `AgentState.closing_seed` →
    `explanation_agent` → `build_explanation`. The dispatcher computes the
    ordinal from the repository (count of prior runs for `session_token`).
    Standalone/test callers default `closing_seed=0`.
  - `_intro_paragraph` gains a **band-aware lead clause** computed from the
    top-ranked `renderable` band already in hand (no new data/LLM call):
    - top band `safe` → confident lead (e.g. "hồ sơ của bạn đang khá cạnh tranh");
    - `match` → balanced lead;
    - `reach`/`unknown` → cautious lead (e.g. "có một vài lựa chọn bạn nên cân
      nhắc kỹ").
    The existing fact list is preserved after the lead clause.
- **Acceptance:** two consecutive advisories in one session (seeds 0,1) do not
  repeat the same closing line; a correction re-run (`correction_note` set)
  emits **no** closing; intro lead wording differs between a `safe`-band and a
  `reach`-band fixture.

## 3e. De-duplicate conflict caveats + add section transitions

- **Now:** `_data_note` (`explanation_service.py:207–234`) emits the full
  "…nhưng bạn nên kiểm tra thông báo tuyển sinh chính thức…" caveat **per
  conflicting program**; section headers like "Không đủ điều kiện xét tuyển"
  (`:337–345`) appear with no connective lead-in.
- **Change (top caveat + short per-program):**
  - When **≥2 renderable candidates carry a data note**, emit **one**
    consolidated caveat near the top of the recommendations block: "Một số
    chương trình dưới đây có dữ liệu chưa thống nhất giữa các nguồn; bạn nên đối
    chiếu thông báo tuyển sinh chính thức trước khi đăng ký." Then shorten each
    per-program `_data_note` to **only its differing values** (which field, which
    sources/values), dropping the repeated "kiểm tra thông báo… chính thức"
    boilerplate.
  - With **0 or 1** conflicting program, behavior is unchanged (the single
    per-program note stays as today, boilerplate included).
  - Add a one-line **bridge** before bare section headers (at minimum before
    "Không đủ điều kiện xét tuyển").
- **Acceptance:** a fixture with N≥2 conflicting programs asserts the full
  "đối chiếu thông báo… chính thức" caveat appears **once** (top), and each
  per-program note no longer repeats that boilerplate; a single-conflict fixture
  is unchanged.

## 3f. Unify "no data" fallbacks to first person

- **Now:** cold "Hệ thống chưa có dữ liệu…" in `knowledge_fanout.py:111` and
  `conversation_service.py:347`. (Empathy-first emotional support and the
  conversational-handler register are **already** implemented — no change.)
- **Change:** rewrite both to first-person mình/bạn, e.g. "Mình hiện chưa có dữ
  liệu về {…}. Bạn có thể liên hệ trực tiếp nhà trường để biết thêm chi tiết."
- **Acceptance:** no user-facing string contains "Hệ thống chưa có"; the no-data
  fallbacks read in first person.

---

## Testing strategy

- 3a ships the grep-guard / string-audit test plus updated wording assertions in
  existing explanation/conversation tests.
- 3c, 3d, 3e ship targeted fixtures asserting their acceptance criteria
  (value-echo + recap; closing rotation/skip + intro band; single top caveat).
- 3b, 3f are covered by string assertions.
- Full `pytest -q` green against `admission_test` after each plan.

## Plan split

Folder `docs/superpowers/plans/2026-06-10-slice3-naturalness-voice/`, four small
independently-mergeable plans:

1. **Register sweep (3a + 3b + 3f)** — pure string rewrites + grep-guard test.
   Lowest risk; do first.
2. **Slot acknowledgement (3c)** — echo + recap in `conversation_service.py`,
   softened `admission_method` prompt in `slots.py`.
3. **Intro + closing (3d)** — `CLOSING_VARIANTS`, band-aware intro lead, and the
   `closing_seed` plumbing through the dispatcher/runner/agent chain.
4. **Caveat dedup (3e)** — top consolidated caveat + shortened per-program notes
   + section bridges in `explanation_service.py`.

## Non-goals

- No change to rankings, eligibility, conflict resolution, or which sources are
  cited.
- No new LLM calls (the intro band and closing seed are computed from data
  already in `AgentState`/`renderable`).
- Model-tier work stays in slice 4.
