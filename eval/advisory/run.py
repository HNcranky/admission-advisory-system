"""Advisory eligibility/constraint eval over synthetic student profiles.

    python -m eval.advisory.run

Recommendation quality has no single ground truth, so this harness measures the
two properties that *can* be checked objectively against the canonical store,
following the standard application-thesis rubric:

  * Constraint satisfaction — every recommended program matches a major the
    student asked for (the system did not propose something off-topic).
  * Eligibility consistency — no program is presented as reachable when the
    applicant's score is below its reference cutoff without an explicit caution
    (the system does not over-promise).
  * Coverage — profiles that should have an eligible match get at least one
    recommendation, and a deliberately unmatchable profile gets none (or a
    transparent no-match), not a fabricated one.

Each profile is seeded directly into the pipeline (`profile_seeded=True`), so the
profile-extraction LLM call is skipped; the reasoning, policy, and explanation
stages still run, so this needs the database up and a Gemini key. Calls are paced
for the free-tier key pool.
"""

import json
import os
import time
from pathlib import Path

PROFILES_PATH = Path("eval/advisory/profiles.json")
REPORT_PATH = Path("docs/superpowers/evals/advisory-eligibility.md")
CALL_DELAY_SECONDS = float(os.getenv("EVAL_CALL_DELAY_SECONDS", "3.0"))


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _matches_major(program_name: str, preferred_majors) -> bool:
    """A recommended program satisfies the major constraint if any requested
    major token is contained in (or contains) the program name."""
    prog = _norm(program_name)
    for major in preferred_majors:
        m = _norm(major)
        if m and (m in prog or prog in m or _token_overlap(m, prog)):
            return True
    return False


def _token_overlap(a: str, b: str) -> bool:
    ta, tb = set(a.split()), set(b.split())
    return len(ta & tb) >= max(1, min(len(ta), len(tb)) // 2)


def _run_profile(profile):
    from domain.models import StudentProfile
    from graph import graph
    from state import AgentState

    seeded = StudentProfile(
        total_score=profile.get("total_score"),
        admission_method=profile.get("admission_method"),
        subject_combination=profile.get("subject_combination"),
        preferred_majors=profile.get("preferred_majors", []),
        preferred_schools=profile.get("preferred_schools", []),
    )
    state = AgentState(
        user_query="(synthetic advisory eval profile)",
        student_profile=seeded,
        profile_seeded=True,
    )
    final = graph.invoke(state)
    return final if isinstance(final, AgentState) else AgentState(**final)


def _evaluate(profile, result):
    candidates_by_id = {c.candidate_id: c for c in result.retrieved_programs}
    recs = result.ranked_recommendations
    preferred = profile.get("preferred_majors", [])

    constraint_ok = 0
    eligibility_ok = 0
    for r in recs:
        cand = candidates_by_id.get(r.candidate_id)
        program_name = cand.program_name if cand else ""
        if _matches_major(program_name, preferred):
            constraint_ok += 1

        assessment = getattr(r, "cutoff_assessment", None)
        below = assessment is not None and assessment.score_fit == "below"
        has_caution = bool(getattr(r, "cautions", []))
        # Eligibility-consistent unless a below-cutoff program is presented with
        # no caution at all.
        if not (below and not has_caution):
            eligibility_ok += 1

    n_recs = len(recs)
    matched = n_recs > 0
    coverage_ok = matched == profile.get("expect_match", True)
    return {
        "id": profile["id"],
        "band": profile.get("band"),
        "n_recs": n_recs,
        "constraint_ok": constraint_ok,
        "eligibility_ok": eligibility_ok,
        "coverage_ok": coverage_ok,
    }


def main() -> None:
    data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    profiles = data["profiles"]

    rows = []
    for profile in profiles:
        try:
            result = _run_profile(profile)
            rows.append(_evaluate(profile, result))
        except Exception as exc:  # noqa: BLE001
            rows.append({"id": profile["id"], "band": profile.get("band"),
                         "n_recs": 0, "constraint_ok": 0, "eligibility_ok": 0,
                         "coverage_ok": False, "error": repr(exc)})
        if CALL_DELAY_SECONDS:
            time.sleep(CALL_DELAY_SECONDS)

    total_recs = sum(r["n_recs"] for r in rows)
    constraint_ok = sum(r["constraint_ok"] for r in rows)
    eligibility_ok = sum(r["eligibility_ok"] for r in rows)
    coverage_ok = sum(1 for r in rows if r["coverage_ok"])

    def pct(num, den):
        return f"{num}/{den} = {num / den:.0%}" if den else "—"

    lines = ["# Advisory eligibility/constraint eval", ""]
    lines.append(
        f"{len(profiles)} synthetic profiles, seeded directly into the advisory "
        "pipeline. Constraint/eligibility are over recommended programs; coverage "
        "is per profile."
    )
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Total recommendations | {total_recs} |")
    lines.append(f"| Constraint satisfaction | {pct(constraint_ok, total_recs)} |")
    lines.append(f"| Eligibility consistency | {pct(eligibility_ok, total_recs)} |")
    lines.append(f"| Coverage (per profile) | {pct(coverage_ok, len(profiles))} |")
    lines.append("")
    lines.append("## Per-profile")
    lines.append("")
    lines.append("| Profile | Band | #Recs | Constraint OK | Eligibility OK | Coverage OK |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        note = f" ({r['error']})" if r.get("error") else ""
        lines.append(
            f"| `{r['id']}`{note} | {r['band']} | {r['n_recs']} | "
            f"{r['constraint_ok']}/{r['n_recs']} | {r['eligibility_ok']}/{r['n_recs']} | "
            f"{'✅' if r['coverage_ok'] else '❌'} |"
        )

    md = "\n".join(lines) + "\n"
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(md, encoding="utf-8")
    print(md)
    print(f"Report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
