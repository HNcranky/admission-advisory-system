from ingestion.registry.models import SourceEntry
from ingestion.models.pipeline_models import FetchResult


def test_source_entry_uses_model_config():
    assert not hasattr(SourceEntry, "Config")
    assert SourceEntry.model_config.get("use_enum_values") is True


def test_fetch_result_uses_model_config():
    assert not hasattr(FetchResult, "Config")
    assert FetchResult.model_config.get("arbitrary_types_allowed") is True
