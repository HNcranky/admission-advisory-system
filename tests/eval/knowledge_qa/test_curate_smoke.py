def test_curate_module_imports():
    import eval.knowledge_qa.curate as curate

    assert callable(curate.main)
    assert curate.SEEDS_PATH.name == "curation_seeds.json"
