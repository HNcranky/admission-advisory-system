# --- input extractors (state slice each node consumes, before it runs) ---

def input_profile(state):
    return {"user_query": state.user_query, "profile_seeded": state.profile_seeded}


def input_retrieve(state):
    return {
        "student_profile": state.student_profile.model_dump(mode="json"),
        "admission_year": state.admission_year,
    }


def input_conflict(state):
    candidates = state.retrieved_programs or []
    return {
        "count": len(candidates),
        "candidates": [c.model_dump(mode="json") for c in candidates],
    }


def input_reason(state):
    return {
        "candidate_count": len(state.retrieved_programs or []),
        "resolution_outcomes": [r.model_dump(mode="json") for r in state.resolution_outcomes or []],
        "student_profile": state.student_profile.model_dump(mode="json"),
    }


def input_policy(state):
    return {
        "conflicts": list(state.conflicts or []),
        "ranked_recommendations": [r.model_dump(mode="json") for r in state.ranked_recommendations or []],
    }


def input_explanation(state):
    decision = state.policy_decision
    return {
        "policy_decision": decision.model_dump(mode="json") if decision else None,
        "ranked_recommendations": [r.model_dump(mode="json") for r in state.ranked_recommendations or []],
    }


# --- output extractors (node result) ---

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
