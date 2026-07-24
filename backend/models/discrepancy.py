# Data models for Module 2 output
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DiscrepancyCandidate:
    """Single discrepancy detected by one or more validation runs."""
    element_name: str
    discrepancy_type: str
    acceptance_criterion_violated: str
    description: str
    natural_language_feedback: str
    severity: str
    confidence_index: float
    status: str  # HIGH / MEDIUM / LOW
    run_count: int  # How many runs identified this


@dataclass
class Module2Output:
    """
    Final output of Module 2.
    Confidence-annotated discrepancy JSON passed to Module 3.
    """
    passed_to_module3: List[dict] = field(default_factory=list)
    needs_human_review: List[dict] = field(default_factory=list)
    discarded: List[dict] = field(default_factory=list)
    total_runs: int = 0
    total_candidates: int = 0

    def summary(self) -> str:
        return (
            f"Total runs: {self.total_runs} | "
            f"HIGH (→Module 3): {len(self.passed_to_module3)} | "
            f"MEDIUM (→Review): {len(self.needs_human_review)} | "
            f"LOW (Discarded): {len(self.discarded)}"
        )