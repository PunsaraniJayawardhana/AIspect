"""
UVRI (UI-Validation Readiness Index) — Module 1's core metric.

UVRI(s) = alpha*C(s) + beta*A(s) + gamma*G(s) + delta*T(s)

Weights are read from config.settings and default to equal
weighting (0.25 each) until replaced with regression/AHP-fitted values
produced by backend/scripts/fit_uvri_weights.py.
"""

from typing import List, Tuple, Dict, Any

from config.settings import (
    UVRI_WEIGHT_COVERAGE,
    UVRI_WEIGHT_SPECIFICITY,
    UVRI_WEIGHT_AMBIGUITY,
    UVRI_WEIGHT_TESTABILITY,
)
from pipeline.module1.coverage_density import compute_coverage_density
from pipeline.module1.assertion_specificity import compute_assertion_specificity
from pipeline.module1.ambiguity_penalty import compute_ambiguity_penalty
from pipeline.module1.testability_score import compute_testability_score


async def compute_uvri(
    acs: List[str],
    screen_type: str,
) -> Tuple[float, Dict[str, Any]]:
    """
    Compute the four UVRI sub-terms and the weighted composite score.

    Returns:
        (uvri, sub) — sub keeps the original flat
        {coverage, specificity, ambiguity, testability} shape for backward
        compatibility with orchestrator.py, plus a nested "details" key
        holding per-term diagnostic data (missing elements, per-AC check
        breakdowns, matched ambiguous terms, etc.) for auditability and
        for the validation scripts.
    """
    coverage, coverage_details = await compute_coverage_density(acs, screen_type)
    specificity, specificity_details = await compute_assertion_specificity(acs)
    ambiguity, ambiguity_details = compute_ambiguity_penalty(acs)
    testability, testability_details = await compute_testability_score(acs)

    uvri = (
        UVRI_WEIGHT_COVERAGE * coverage
        + UVRI_WEIGHT_SPECIFICITY * specificity
        + UVRI_WEIGHT_AMBIGUITY * ambiguity
        + UVRI_WEIGHT_TESTABILITY * testability
    )

    sub = {
        "coverage": coverage,
        "specificity": specificity,
        "ambiguity": ambiguity,
        "testability": testability,
        "details": {
            "coverage": coverage_details,
            "specificity": specificity_details,
            "ambiguity": ambiguity_details,
            "testability": testability_details,
        },
    }

    return uvri, sub
