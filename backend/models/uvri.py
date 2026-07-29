"""Typed result container for a UVRI computation."""

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class UVRIResult:
    uvri: float
    coverage: float
    specificity: float
    ambiguity: float
    testability: float
    details: Dict[str, Any] = field(default_factory=dict)

    def to_subterms_dict(self) -> Dict[str, float]:
        """Matches the flat {coverage, specificity, ambiguity, testability}
        shape the orchestrator already persists to disk, for backward
        compatibility with existing consumers of uvri_pre/uvri_post."""
        return {
            "coverage": self.coverage,
            "specificity": self.specificity,
            "ambiguity": self.ambiguity,
            "testability": self.testability,
        }
