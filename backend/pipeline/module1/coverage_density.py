"""
Coverage Density — C(s) — UVRI sub-term.

C(s) = |UI elements referenced in ACs| / |UI elements expected for screen type|

Denominator comes from backend/lexicons/screen_element_taxonomy.py (fixed,
external ground truth, independent of what the story says). Numerator is
determined by asking the LLM which of those exact reference elements are
explicitly named in the ACs — binding the LLM's output directly to the
taxonomy vocabulary avoids a separate fuzzy-matching step.
"""

from typing import List, Tuple, Dict, Any
from backend.integrations.claude_client import call_claude_json
from backend.config.settings import MODULE1_MODEL
from backend.lexicons.screen_element_taxonomy import get_expected_elements
from backend.prompts.module1_uvri_prompts import (
    COVERAGE_SYSTEM_PROMPT,
    build_coverage_user_prompt,
)


async def compute_coverage_density(
    acs: List[str],
    screen_type: str,
) -> Tuple[float, Dict[str, Any]]:
    """
    Returns:
        (coverage_score, details) where details contains the expected
        element list, which were found referenced, and which are missing.
    """
    expected_elements = get_expected_elements(screen_type)

    if not acs or not expected_elements:
        return 0.0, {
            "expected_elements": expected_elements,
            "referenced_elements": [],
            "missing_elements": expected_elements,
        }

    user_prompt = build_coverage_user_prompt(acs, expected_elements)

    try:
        response = await call_claude_json(
            model=MODULE1_MODEL,
            system_prompt=COVERAGE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=1024,
            temperature=0.0,
        )
    except RuntimeError as e:
        print(f"[coverage_density] Claude call failed: {e}")
        return 0.0, {
            "expected_elements": expected_elements,
            "referenced_elements": [],
            "missing_elements": expected_elements,
            "error": str(e),
        }

    if not isinstance(response, list):
        print(f"[coverage_density] Expected list, got {type(response).__name__}")
        return 0.0, {
            "expected_elements": expected_elements,
            "referenced_elements": [],
            "missing_elements": expected_elements,
        }

    referenced: List[str] = []
    for item in response:
        if not isinstance(item, dict):
            continue
        if item.get("referenced") is True and isinstance(item.get("element"), str):
            referenced.append(item["element"])

    missing = [el for el in expected_elements if el not in referenced]
    coverage = len(referenced) / len(expected_elements)

    return coverage, {
        "expected_elements": expected_elements,
        "referenced_elements": referenced,
        "missing_elements": missing,
    }
