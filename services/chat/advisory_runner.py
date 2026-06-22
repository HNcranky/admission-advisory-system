from domain.models import StudentProfile
from graph import graph
from state import AgentState


def run_advisory_for_session(profile_state, latest_user_message: str, trace_run_id: int | None = None,
                             correction_note: dict | None = None, closing_seed: int = 0):
    student_profile = StudentProfile(
        total_score=profile_state.total_score,
        admission_method=profile_state.admission_method,
        subject_combination=profile_state.subject_combination,
        preferred_majors=profile_state.preferred_majors,
        preferred_schools=profile_state.preferred_schools,
        location_preference=profile_state.location_preference,
        tuition_budget=profile_state.tuition_budget,
        constraints=profile_state.constraints,
        missing_slots=profile_state.missing_slots,
    )

    state = AgentState(
        user_query=latest_user_message,
        admission_year=profile_state.admission_year or 2026,
        student_profile=student_profile,
        profile_seeded=True,
        trace_run_id=trace_run_id,
        correction_note=correction_note,
        closing_seed=closing_seed,
    )

    return graph.invoke(state)
