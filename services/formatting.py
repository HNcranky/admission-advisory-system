from typing import Any

from agents.models import CandidateProgram


def fmt_num(value: Any) -> str:
    """27.0 -> '27', 25.75 -> '25.75'."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def program_label(candidate: CandidateProgram) -> str:
    """Tên ngành hiển thị: program_name_raw (tên thực của trường) ưu tiên,
    fallback program_name (canonical) khi raw rỗng/null."""
    raw = (candidate.program_name_raw or "").strip()
    return raw or candidate.program_name
