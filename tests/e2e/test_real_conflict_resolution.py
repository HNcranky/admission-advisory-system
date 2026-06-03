import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.requires_real_dataset

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "real_dataset_dump.sql"


def _real_dataset_available() -> bool:
    return bool(os.getenv("DATABASE_URL")) and FIXTURE_PATH.exists()


@pytest.mark.skipif(
    not _real_dataset_available(),
    reason="DATABASE_URL and tests/e2e/fixtures/real_dataset_dump.sql are required",
)
def test_real_conflict_resolution_reaches_final_answer(monkeypatch):
    monkeypatch.delenv("ADVISORY_MOCK_CONFLICTS", raising=False)

    from graph import graph
    from state import AgentState

    result = graph.invoke(
        AgentState(user_query="Tu van nganh Cong nghe thong tin UET nam 2026").model_dump()
    )

    assert result.get("resolution_outcomes")
    assert result.get("final_answer")
    assert "Xác minh dữ liệu" in result["final_answer"]
