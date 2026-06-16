def test_agents_models_shim_reexports_domain_models():
    from domain.models import CandidateProgram as ShimCP
    from domain.models import CandidateProgram as DomainCP
    assert ShimCP is DomainCP


def test_all_eight_symbols_importable_via_shim():
    import agents.models as shim
    for name in (
        "CandidateProgram", "CutoffAssessment", "CutoffEntry",
        "EligibilityCheck", "Evidence", "PolicyDecision",
        "RankedRecommendation", "StudentProfile",
    ):
        assert hasattr(shim, name), name
