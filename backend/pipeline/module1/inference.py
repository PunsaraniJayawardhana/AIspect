"""
Implicit UI Element Inference — Module 1's research contribution.

Given a user story's text, navigation path, screen type, and explicit
acceptance criteria, this module uses Claude to identify statically visible
UI elements that an experienced QA engineer would universally expect on the
described screen type but that are MISSING from the written acceptance
criteria.

The inferred elements are returned as AC-format strings ready to be merged
with the explicit AC list before being passed to Module 2.
"""

from typing import List, Dict, Any
from integrations.claude_client import call_claude_json
from config.settings import MODULE1_MODEL


SYSTEM_PROMPT = """You are a senior Quality Assurance engineer with 10+ years of experience auditing web and mobile UI designs against requirements.

Your task is to identify STATICALLY VISIBLE UI elements that an experienced QA engineer would universally expect on a given screen type, but which are MISSING from the written acceptance criteria.

CRITICAL CONSTRAINTS:
1. Only suggest STATICALLY VISIBLE elements — elements that would appear on a single static screenshot of the design in its default state.
2. DO NOT suggest:
   - Error states or validation messages (these are state-dependent)
   - Loading indicators or spinners (these are state-dependent)
   - Hover effects, focus states, or animations (these are interaction-dependent)
   - Multi-step flows or screens that follow this one
   - Backend logic, API behaviours, or data validation rules
3. Only suggest elements that are GENUINELY EXPECTED on this type of screen by industry convention — not theoretically possible elements.
4. DO NOT duplicate or rephrase elements already covered by the explicit acceptance criteria.
5. Each suggestion must be specific, concrete, and visually verifiable.

OUTPUT FORMAT:
Return ONLY a valid JSON array. Each item must be an object with two keys:
- "element": a brief name for the UI element (e.g., "Password show/hide toggle")
- "ac_format": the same element rewritten as a testable acceptance criterion (e.g., "Password field should include a show/hide toggle icon to reveal the entered password")

DO NOT include any explanation, preamble, or text outside the JSON array. DO NOT wrap the response in Markdown code fences."""


def _build_user_prompt(
    story_text: str,
    nav_path: str,
    screen_type: str,
    explicit_ACs: List[str],
) -> str:
    """Build the user-side prompt with the story context and explicit ACs."""
    ac_block = "\n".join(f"  - {ac}" for ac in explicit_ACs) or "  (none)"
    return f"""Analyse the following user story and identify implicit UI elements that are MISSING from the explicit acceptance criteria but would be universally expected on this screen type.

SCREEN TYPE: {screen_type}
NAVIGATION PATH: {nav_path}

USER STORY:
{story_text}

EXPLICIT ACCEPTANCE CRITERIA:
{ac_block}

Now identify the statically visible UI elements that an experienced QA engineer would expect on this {screen_type} screen but that are NOT covered above. Return only the JSON array as specified."""


async def infer_implicit_elements(
    parsed: Dict[str, Any],
    screen_type: str,
) -> List[str]:
    """
    Run the Implicit UI Element Inference engine for one user story.

    Args:
        parsed: The output of parse_adf(), containing story_text, nav_path,
                and explicit_ACs.
        screen_type: The classified screen type, e.g. "signup", "login".

    Returns:
        A list of inferred ACs as plain strings, ready to be concatenated
        with the explicit ACs to form the enriched requirement set.
    """
    story_text = parsed.get("story_text", "").strip()
    nav_path = parsed.get("nav_path", "").strip()
    explicit_ACs = parsed.get("explicit_ACs", []) or []

    # If there's no story text and no ACs, there's nothing to reason about.
    if not story_text and not explicit_ACs:
        return []

    user_prompt = _build_user_prompt(
        story_text=story_text,
        nav_path=nav_path,
        screen_type=screen_type,
        explicit_ACs=explicit_ACs,
    )

    try:
        response = await call_claude_json(
            model=MODULE1_MODEL,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=2048,
            temperature=0.0,
        )
    except RuntimeError as e:
        # Inference failed — log and return empty rather than crashing
        # the whole pipeline. Module 2 can still proceed with just explicit ACs.
        print(f"[inference] Claude call failed: {e}")
        return []

    # Defensive parsing: response should be a list of {element, ac_format} dicts
    if not isinstance(response, list):
        print(f"[inference] Expected list, got {type(response).__name__}")
        return []

    inferred_acs: List[str] = []
    for item in response:
        if not isinstance(item, dict):
            continue
        ac_text = item.get("ac_format")
        if isinstance(ac_text, str) and ac_text.strip():
            inferred_acs.append(ac_text.strip())

    return inferred_acs