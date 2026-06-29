"""Synthetic conflict scenarios for the deterministic conflict service.

Real contradictions between official sources are rare in the current corpus, so
the conflict pipeline (`services/conflict/`) cannot be exercised by the live data
alone. This module injects controlled scenarios — two sources publishing
different quota or cutoff values for the same program — and measures whether the
pipeline (a) detects the contradiction, (b) avoids flagging agreeing sources, and
(c) resolves or transparently surfaces each case. The pipeline is fully
deterministic (no LLM), so the results are exact and reproducible.

Each scenario is a list of `CandidateProgram` records for one (school, year,
program, method) group plus the ground-truth label of whether it should conflict.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from domain.models import CandidateProgram, CutoffEntry, Evidence


def _quota_candidate(
    cid: str,
    program: str,
    quota_value: Optional[int],
    source_url: str,
    trust_level: int,
    confidence: float = 0.8,
    fetched_at: Optional[datetime] = None,
) -> CandidateProgram:
    return CandidateProgram(
        candidate_id=cid,
        school_id="hust",
        school_name="HUST",
        admission_year=2025,
        program_id="IT1",
        program_name=program,
        admission_method="thpt_score",
        quota=({"value": quota_value} if quota_value is not None else None),
        evidence=[
            Evidence(
                source_url=source_url,
                school_name="HUST",
                admission_year=2025,
                field_name="quota",
                normalized_value=quota_value,
                confidence_score=confidence,
                trust_level=trust_level,
            )
        ],
    )


def _cutoff_candidate(
    cid: str,
    program: str,
    cutoff_score: float,
    source_url: str,
    trust_level: int,
) -> CandidateProgram:
    return CandidateProgram(
        candidate_id=cid,
        school_id="hust",
        school_name="HUST",
        admission_year=2025,
        program_id="IT1",
        program_name=program,
        admission_method="thpt_score",
        cutoff_history=[
            CutoffEntry(
                cutoff_year=2024,
                admission_method="thpt_score",
                cutoff_score=cutoff_score,
                source_url=source_url,
                trust_level=trust_level,
            )
        ],
    )


@dataclass
class ConflictScenario:
    key: str
    field: str  # "quota" | "cutoff_score"
    description: str
    candidates: List[CandidateProgram]
    should_conflict: bool
    # For decision-changing cutoff cases, a profile score that splits the labels.
    profile_score: Optional[float] = None


_OFFICIAL = "https://ts.hust.edu.vn/de-an-2025"
_PROPOSAL = "https://ts.hust.edu.vn/proposal-2025.pdf"
_AGGREGATOR = "https://tuyensinh247.example/hust"


SCENARIOS: List[ConflictScenario] = [
    # --- True conflicts (should be detected) ---
    ConflictScenario(
        key="quota_120_vs_140_trust_split",
        field="quota",
        description="CS quota: official page 120 (trust 3) vs aggregator 140 (trust 1).",
        candidates=[
            _quota_candidate("c1", "Khoa học máy tính", 120, _OFFICIAL, trust_level=3),
            _quota_candidate("c2", "Khoa học máy tính", 140, _AGGREGATOR, trust_level=1),
        ],
        should_conflict=True,
    ),
    ConflictScenario(
        key="quota_120_vs_140_equal_trust",
        field="quota",
        description="CS quota: two equally-trusted sources disagree (120 vs 140).",
        candidates=[
            _quota_candidate("c1", "Khoa học máy tính", 120, _OFFICIAL, trust_level=3),
            _quota_candidate("c2", "Khoa học máy tính", 140, _PROPOSAL, trust_level=3),
        ],
        should_conflict=True,
    ),
    ConflictScenario(
        key="quota_three_way",
        field="quota",
        description="CS quota: three sources, two agree on 120, one says 150.",
        candidates=[
            _quota_candidate("c1", "Khoa học máy tính", 120, _OFFICIAL, trust_level=2),
            _quota_candidate("c2", "Khoa học máy tính", 120, _PROPOSAL, trust_level=2),
            _quota_candidate("c3", "Khoa học máy tính", 150, _AGGREGATOR, trust_level=2),
        ],
        should_conflict=True,
    ),
    ConflictScenario(
        key="cutoff_decisive_same_label",
        field="cutoff_score",
        description="Cutoff 2024: 27.5 vs 27.6 — different sources, same admit/reject label.",
        candidates=[
            _cutoff_candidate("c1", "Khoa học máy tính", 27.5, _OFFICIAL, trust_level=3),
            _cutoff_candidate("c2", "Khoa học máy tính", 27.6, _AGGREGATOR, trust_level=1),
        ],
        should_conflict=True,
        profile_score=29.0,  # above both → label unchanged → resolvable
    ),
    ConflictScenario(
        key="cutoff_decision_changing",
        field="cutoff_score",
        description="Cutoff 2024: 26.0 vs 28.0 — straddles the applicant's score (decision-changing).",
        candidates=[
            _cutoff_candidate("c1", "Khoa học máy tính", 26.0, _OFFICIAL, trust_level=2),
            _cutoff_candidate("c2", "Khoa học máy tính", 28.0, _AGGREGATOR, trust_level=2),
        ],
        should_conflict=True,
        profile_score=27.0,  # above 26 but below 28 → must be surfaced, not silently resolved
    ),
    # --- Negative controls (must NOT be flagged) ---
    ConflictScenario(
        key="quota_agree",
        field="quota",
        description="CS quota: two sources both say 120 (no conflict).",
        candidates=[
            _quota_candidate("c1", "Khoa học máy tính", 120, _OFFICIAL, trust_level=3),
            _quota_candidate("c2", "Khoa học máy tính", 120, _AGGREGATOR, trust_level=1),
        ],
        should_conflict=False,
    ),
    ConflictScenario(
        key="cutoff_agree",
        field="cutoff_score",
        description="Cutoff 2024: both sources say 27.5 (no conflict).",
        candidates=[
            _cutoff_candidate("c1", "Khoa học máy tính", 27.5, _OFFICIAL, trust_level=3),
            _cutoff_candidate("c2", "Khoa học máy tính", 27.5, _AGGREGATOR, trust_level=1),
        ],
        should_conflict=False,
    ),
    ConflictScenario(
        key="quota_single_source",
        field="quota",
        description="CS quota from one source only (nothing to conflict with).",
        candidates=[
            _quota_candidate("c1", "Khoa học máy tính", 120, _OFFICIAL, trust_level=3),
        ],
        should_conflict=False,
    ),
]
