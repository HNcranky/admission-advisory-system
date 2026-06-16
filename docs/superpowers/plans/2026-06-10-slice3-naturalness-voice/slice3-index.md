# Slice 3 — Naturalness / Voice — Plan Index

**Spec:** `docs/superpowers/specs/2026-06-10-slice3-naturalness-voice-design.md`
**Parent spec:** `docs/superpowers/specs/2026-06-10-answer-quality-cost-naturalness-design.md`

Slice 3 is split into six small, independently-mergeable plans. Each ships its
own tests and leaves `pytest -q` green.

## Plans (recommended order)

| # | Plan | Scope | Risk |
|---|------|-------|------|
| 1 | [slice3a-register-sweep](slice3a-register-sweep.md) | Rewrite every bot→user "em" → "bạn" (`explanation_service.py`, `conversation_service.py:241`, `messages.js` title) + a behavioral register-audit test | low |
| 2 | [slice3b-error-message-diacritics](slice3b-error-message-diacritics.md) | Fix de-accented advisory-failure message in `run_dispatcher.py` | trivial |
| 3 | [slice3f-no-data-first-person](slice3f-no-data-first-person.md) | "Hệ thống chưa có dữ liệu" → first-person "Mình hiện chưa có…" in `knowledge_fanout.py` + `conversation_service.py` | trivial |
| 4 | [slice3c-slot-acknowledgement](slice3c-slot-acknowledgement.md) | Echo captured slot value + ≥2-slot recap before next question; soften `admission_method` prompt | medium |
| 5 | [slice3d-intro-band-closing-rotation](slice3d-intro-band-closing-rotation.md) | Band-aware intro lead; rotating/skip-on-correction closing + `closing_seed` plumbing | medium |
| 6 | [slice3e-caveat-dedup](slice3e-caveat-dedup.md) | One consolidated conflict caveat when ≥2 programs conflict; shorten per-program notes; section bridges | medium |

## Ordering rationale

- **3a first.** It rewrites string literals across `explanation_service.py`
  (including `CLOSING_QUESTION`). Plans 5 (3d) and 6 (3e) further edit those same
  functions; doing the pronoun sweep first means later plans build on the final
  wording and avoid re-touching the same lines.
- **3b, 3f next** — trivial, isolated string fixes, no overlap with anything.
- **3c, 3d, 3e** — behavioral changes, each in its own area; order among them is
  flexible but listed by increasing surface area.

## Slice-wide invariant

No plan changes any *decision* — rankings, eligibility, conflict resolution, or
which sources are cited. Only user-visible wording and the (rare) closing-line
presence change. Full `pytest -q` against `admission_test` stays green after
each plan.
