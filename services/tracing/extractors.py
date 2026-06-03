def extract_profile(result, state):
    return {"student_profile": result.student_profile.model_dump(mode="json")}


def extract_candidates(result, state):
    candidates = result.retrieved_programs or []
    return {
        "count": len(candidates),
        "candidates": [c.model_dump(mode="json") for c in candidates],
    }


def extract_conflicts(result, state):
    return {
        "resolution_outcomes": [r.model_dump(mode="json") for r in result.resolution_outcomes or []],
    }


def extract_reasoning(result, state):
    return {
        "eligibility_checks": [c.model_dump(mode="json") for c in result.eligibility_checks or []],
        "ranked_recommendations": [r.model_dump(mode="json") for r in result.ranked_recommendations or []],
    }


def extract_policy(result, state):
    decision = result.policy_decision
    return {
        "policy_decision": decision.model_dump(mode="json") if decision else None,
        "filtered_recommendations": [r.model_dump(mode="json") for r in result.ranked_recommendations or []],
    }


def extract_explanation(result, state):
    return {
        "final_answer": result.final_answer or "",
        "evidence": [e.model_dump(mode="json") for e in result.citations or []],
    }
