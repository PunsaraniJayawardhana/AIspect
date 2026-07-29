"""
Testability Score — T(s) — UVRI sub-term.

T(s) = |ACs with pass/fail assertion| / n

The one term relying on LLM judgement rather than deterministic
computation — deliberately isolated to its own term and weighted equally
with the others rather than given extra influence, per the design in
What_is_UVRI.pdf. Also the direct forward-looking signal for Module 3's
Cypress test generation reliability.
"""

from typing import List, Tuple, Dict, Any
from integrations.claude_client import call_claude_json
from config.settings import MODULE1_MODEL
from prompts.module1_uvri_prompts import (
    TESTABILITY_SYSTEM_PROMPT,
    build_testability_user_prompt,
)


async def compute_testability_score(
    acs: List[str],
) -> Tuple[float, Dict[str, Any]]:
    if not acs:
        return 0.0, {"per_ac": []}

    user_prompt = build_testability_user_prompt(acs)

    max_tokens = min(8192, 256 + 40 * len(acs))

    try:
        response = await call_claude_json(
            model=MODULE1_MODEL,
            system_prompt=TESTABILITY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=0.0,
        )
    except RuntimeError as e:
        print(f"[testability_score] Claude call failed: {e}")
        return 0.0, {"per_ac": [], "error": str(e)}

    if not isinstance(response, list):
        print(f"[testability_score] Expected list, got {type(response).__name__}")
        return 0.0, {"per_ac": []}

    if len(response) < len(acs):
        print(f"[testability_score] WARNING: got {len(response)} results for "
              f"{len(acs)} ACs — response may have been truncated.")

    per_ac: List[Dict[str, Any]] = []
    for item in response:
        if not isinstance(item, dict):
            continue
        per_ac.append({
            "ac": item.get("ac", ""),
            "testable": bool(item.get("testable", False)),
        })

    if not per_ac:
        return 0.0, {"per_ac": []}

    testable_count = sum(1 for entry in per_ac if entry["testable"])
    testability = testable_count / len(per_ac)

    return testability, {"per_ac": per_ac}
