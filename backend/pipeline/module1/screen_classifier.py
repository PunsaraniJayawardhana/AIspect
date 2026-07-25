"""
Screen type classifier — Module 1.

Classifies a Jira user story into one of a fixed taxonomy of screen types
(login, signup, home, listing, detail, form, dashboard, search, checkout,
profile, settings, generic). Uses a small LLM call grounded by the story
text and nav path.

Returning a label that exists in the taxonomy is important because the
UVRI Coverage Density term (built next) uses this label as the key into
the expected-UI-elements taxonomy. Classifier output must be predictable.
"""

from typing import Dict, Any
from integrations.claude_client import call_claude_json
from config.settings import MODULE1_MODEL


SCREEN_TYPES = [
    "login",
    "signup",
    "home",
    "listing",
    "detail",
    "form",
    "dashboard",
    "search",
    "checkout",
    "profile",
    "settings",
    "entity_crud",
    "generic",
]


SYSTEM_PROMPT = """You classify user-interface screens into a fixed taxonomy of screen types.

You will be given a user-story description and a navigation path. Return the single screen type that best matches.

The taxonomy is:
- login: an authentication screen for existing users (email/password sign-in, social sign-in)
- signup: an account-creation screen (registration form, OAuth sign-up)
- home: the main landing or home page of an application (typically has hero banner, category navigation, featured products/content)
- listing: a screen that displays a list of items (product catalogue, search results, item grid)
- detail: a screen showing the full details of one item (product detail page, article view)
- form: a generic data-entry screen that does not match login/signup/checkout (e.g. contact form, feedback form, profile editor)
- dashboard: an authenticated overview screen with stats, widgets, or summary panels
- search: a dedicated search interface with filters and results
- checkout: a screen for completing a purchase (cart review, payment, shipping)
- profile: a screen displaying or editing a user's own profile information
- settings: a screen for configuring application or account preferences
- entity_crud: an authenticated internal screen providing full CRUD (create/read/update/delete) management for a specific entity or record type, typically via a data table with per-row action icons (edit/delete/view) and modal/popup forms for add/edit/view/delete operations (e.g. admin account management, user/member management, book/inventory management, category management)
- generic: use only if none of the above clearly applies

Return ONLY a valid JSON object with a single key "screen_type" whose value is one of the labels above.
Do not wrap in Markdown code fences. Do not add explanation."""


async def classify_screen_type(parsed: Dict[str, Any]) -> str:
    """
    Classify a user story's screen type using the LLM.

    Args:
        parsed: Output of parse_adf(), containing story_text and nav_path.

    Returns:
        One of SCREEN_TYPES. Falls back to "generic" if the LLM returns
        an invalid label or the call fails.
    """
    story_text = parsed.get("story_text", "").strip()
    nav_path = parsed.get("nav_path", "").strip()
    context = parsed.get("context", "").strip()

    user_prompt = f"""NAVIGATION PATH: {nav_path or "(none)"}

CONTEXT: {context or "(none)"}

USER STORY:
{story_text or "(empty)"}

Classify this screen. Return only JSON: {{"screen_type": "..."}}."""

    try:
        response = await call_claude_json(
            model=MODULE1_MODEL,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=64,
            temperature=0.0,
        )
    except RuntimeError as e:
        print(f"[screen_classifier] Claude call failed: {e}")
        return "generic"

    if not isinstance(response, dict):
        return "generic"

    label = response.get("screen_type", "")
    if isinstance(label, str) and label in SCREEN_TYPES:
        return label

    return "generic"