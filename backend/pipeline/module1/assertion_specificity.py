"""
Assertion Specificity — A(s) — UVRI sub-term.

A(s) = (1/n) * sum(specificity(ac_i))

Each AC's specificity is the average of four binary checks (each worth 0.25),
judged by the LLM at temperature 0 for determinism. The averaging itself is
pure arithmetic, isolated from LLM judgement, matching the design in
What_is_UVRI.pdf.
"""

from typing import List, Tuple, Dict, Any
from backend.integrations.claude_client import call_claude_json
from backend.config.settings import MODULE1_MODEL
from backend.prompts.module1_uvri_prompts import (
    SPECIFICITY_SYSTEM_PROMPT,
    build_specificity_user_prompt,
)

_CHECK_KEYS = ["names_element", "observable_state", "concrete_value", "measurable_outcome"]


async def compute_assertion_specificity(
    acs: List[str],
) -> Tuple[float, Dict[str, Any]]:
    if not acs:
        return 0.0, {"per_ac": []}

    user_prompt = build_specificity_user_prompt(acs)

    # Scale the token budget with AC count instead of a fixed cap — a fixed
    # 2048 silently truncates on larger real-world tickets (observed: 40 ACs
    # produced an unparseable, cut-off response, collapsing this term to 0.0
    # with no error surfaced).
    max_tokens = min(8192, 512 + 80 * len(acs))

    try:
        response = await call_claude_json(
            model=MODULE1_MODEL,
            system_prompt=SPECIFICITY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            temperature=0.0,
        )
    except RuntimeError as e:
        print(f"[assertion_specificity] Claude call failed: {e}")
        return 0.0, {"per_ac": [], "error": str(e)}

    if not isinstance(response, list):
        print(f"[assertion_specificity] Expected list, got {type(response).__name__}")
        return 0.0, {"per_ac": []}

    if len(response) < len(acs):
        print(f"[assertion_specificity] WARNING: got {len(response)} results for "
              f"{len(acs)} ACs — response may have been truncated.")

    per_ac: List[Dict[str, Any]] = []
    for item in response:
        if not isinstance(item, dict):
            continue
        checks = {k: bool(item.get(k, False)) for k in _CHECK_KEYS}
        score = 0.25 * sum(checks.values())
        per_ac.append({"ac": item.get("ac", ""), "checks": checks, "score": score})

    if not per_ac:
        return 0.0, {"per_ac": []}

    specificity = sum(entry["score"] for entry in per_ac) / len(per_ac)
    return specificity, {"per_ac": per_ac}
