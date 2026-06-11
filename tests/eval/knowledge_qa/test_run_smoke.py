def test_run_module_exposes_main():
    import eval.knowledge_qa.run as run

    assert callable(run.main)
    assert "gemini-2.5-flash" in run.MODELS
    assert "gemini-2.5-flash-lite" in run.MODELS
    assert run.BASELINE == "gemini-2.5-flash"
