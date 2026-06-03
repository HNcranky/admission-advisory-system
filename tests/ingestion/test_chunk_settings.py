from ingestion.config import settings


def test_chunk_size_default():
    assert settings.CHUNK_SIZE == 1800


def test_chunk_overlap_default():
    assert settings.CHUNK_OVERLAP == 256
