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
from backend.integrations.claude_client import call_claude_json
from backend.config.settings import MODULE1_MODEL


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
5. GROUND your suggestions in the CONTEXT provided, when given. If the context already states a specific mechanism for something (e.g. a specific navigation method, a specific access pattern), do NOT suggest a redundant or conflicting alternative for the same purpose. For example, if the context states the screen is accessed via a sidebar item, do not separately suggest a breadcrumb trail for wayfinding unless the story or context specifically indicates both are used together in this application.
6. DO NOT presuppose or invent domain concepts, data attributes, or business rules that are not evidenced ANYWHERE in the story, context, or explicit acceptance criteria. Only suggest elements that are a structural/layout consequence of what is already described — never elements that imply additional data the system may not actually have. For example, if the story and ACs only ever refer to a single flat account type (e.g. "admin"), do NOT suggest a "Role" selector or role-tier field, since that presupposes a multi-role permission model that was never stated. Passing mention of an unrelated attribute (e.g. a "role" shown only in an audit/"saved by" context) is NOT evidence that the entity itself has selectable role tiers — do not generalise from it.
7. Each suggestion must be specific, concrete, and visually verifiable.
8. Password-type input fields are conventionally expected to display masked input (dots or asterisks) by default — this is a statically visible default-state property, not a validation/error state, and should be suggested when a password field is present in the explicit ACs without any mention of masking.

OUTPUT FORMAT:
Return ONLY a valid JSON array. Each item must be an object with two keys:
- "element": a brief name for the UI element (e.g., "Password show/hide toggle")
- "ac_format": the same element rewritten as a testable acceptance criterion

CRITICAL PHRASING RULE for "ac_format":
Write every acceptance criterion as a DECLARATIVE, PRESENT-TENSE statement of
observable fact — describing what the screen DOES or DISPLAYS, not what it
"should" or "shall" do. Avoid weak/non-binding modal verbs entirely
("should", "may", "could", "might"). State the expected behaviour directly,
as if describing the design as already correct.

Good examples (declarative, present tense, concrete):
  - "The password field includes a show/hide toggle icon to reveal the entered password."
  - "The search results page displays a maximum of 20 results per page with pagination controls."
  - "The sign up screen displays the platform logo above the registration form."

Bad examples (avoid this phrasing):
  - "Password field should include a show/hide toggle icon" (weak modal "should")
  - "The screen should look appropriate" (weak modal + vague adjective)
  - "The page may show a logo" (weak modal "may")

Each ac_format must also name a specific, concrete, and visually verifiable
detail (not just "displays a title" but "displays a prominent title such as
'Create Account' at the top of the form").

DO NOT include any explanation, preamble, or text outside the JSON array. DO NOT wrap the response in Markdown code fences."""


def _build_user_prompt(
    story_text: str,
    context: str,
    nav_path: str,
    screen_type: str,
    explicit_ACs: List[str],
) -> str:
    """Build the user-side prompt with the story context and explicit ACs."""
    ac_block = "\n".join(f"  - {ac}" for ac in explicit_ACs) or "  (none)"
    return f"""Analyse the following user story and identify implicit UI elements that are MISSING from the explicit acceptance criteria but would be universally expected on this screen type.

SCREEN TYPE: {screen_type}
NAVIGATION PATH: {nav_path}

CONTEXT: {context or "(none)"}

USER STORY:
{story_text}

EXPLICIT ACCEPTANCE CRITERIA:
{ac_block}

Now identify the statically visible UI elements that an experienced QA engineer would expect on this {screen_type} screen but that are NOT covered above. Ground your suggestions in the CONTEXT above where relevant — do not suggest elements that conflict with or duplicate a mechanism the context already establishes. Return only the JSON array as specified."""


async def infer_implicit_elements(
    parsed: Dict[str, Any],
    screen_type: str,
) -> List[str]:
    story_text = parsed.get("story_text", "").strip()
    context = parsed.get("context", "").strip()
    nav_path = parsed.get("nav_path", "").strip()
    explicit_ACs = parsed.get("explicit_ACs", []) or []

    if not story_text and not explicit_ACs:
        return []

    user_prompt = _build_user_prompt(
        story_text=story_text,
        context=context,
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
        print(f"[inference] Claude call failed: {e}")
        return []

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
