import json
from pathlib import Path
from typing import Optional

from eval.knowledge_qa.models import GoldenCase

DEFAULT_GOLDEN_PATH = Path(__file__).resolve().parent / "golden_set.json"


def load_golden_set(path: Optional[Path] = None) -> list[GoldenCase]:
    """Load and validate the golden set. Raises on malformed JSON or schema
    violations so a broken fixture fails loudly rather than silently skewing the
    eval."""
    path = path or DEFAULT_GOLDEN_PATH
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [GoldenCase.model_validate(case) for case in data["cases"]]
