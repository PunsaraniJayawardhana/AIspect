"""
Reference taxonomy of expected UI elements per screen type — the ground
truth denominator for the UVRI Coverage Density term, C(s).

Keys MUST exactly match backend/pipeline/module1/screen_classifier.py's
SCREEN_TYPES list, since the classifier's output is used directly as the
lookup key here.

This taxonomy should be treated as a living artefact: build/refine it via
a small corpus study (a sample of real designs + tickets per screen type),
have a second person independently review it, and document the review
process in the report as inter-rater reliability evidence for this
denominator (see the "lexicon/taxonomy validation" step in the methodology).
"""

from typing import Dict, List


SCREEN_ELEMENT_TAXONOMY: Dict[str, List[str]] = {
    "login": [
        "email or username field",
        "password field",
        "password show/hide toggle",
        "login/submit button",
        "forgot password link",
        "remember me checkbox",
        "sign up redirect link",
        "page title or logo",
        "social/third-party login option",
    ],
    "signup": [
        "name field",
        "email field",
        "password field",
        "password show/hide toggle",
        "confirm password field",
        "create account button",
        "third-party auth option (e.g. Google)",
        "terms and conditions checkbox",
        "already have an account link",
        "page title or logo",
    ],
    "home": [
        "navigation bar",
        "hero banner",
        "category navigation",
        "featured items section",
        "search bar",
        "footer",
        "logo",
        "call-to-action button",
    ],
    "listing": [
        "item card grid or list",
        "item thumbnail image",
        "item title",
        "item price or key attribute",
        "filter controls",
        "sort control",
        "pagination or load-more control",
        "search bar",
    ],
    "detail": [
        "item title",
        "item image or gallery",
        "item description",
        "price or key attribute",
        "primary action button (e.g. Add to Cart)",
        "breadcrumb or back navigation",
        "related items section",
    ],
    "form": [
        "field labels",
        "input fields matching described data",
        "submit button",
        "cancel or back control",
        "required-field indicators",
        "placeholder text",
    ],
    "dashboard": [
        "summary/stat widgets",
        "navigation sidebar or menu",
        "chart or graph panel",
        "recent activity section",
        "user account indicator",
        "page title",
    ],
    "search": [
        "search input field",
        "search submit control",
        "filter controls",
        "results list or grid",
        "no-results state indicator",
        "sort control",
    ],
    "checkout": [
        "order summary section",
        "shipping information fields",
        "payment information fields",
        "place order/pay button",
        "price/total breakdown",
        "back to cart link",
    ],
    "profile": [
        "user avatar/photo",
        "user name/display name",
        "editable profile fields",
        "save/update button",
        "account information section",
    ],
    "settings": [
        "settings category navigation",
        "toggle/checkbox controls",
        "save/apply button",
        "section headings",
    ],
    "entity_crud": [
        "page heading/title",
        "add/create button",
        "search or filter input",
        "data table with column headers",
        "per-row action icons (edit/delete/view)",
        "pagination controls",
        "add/create modal or popup form",
        "edit/update modal or popup form",
        "delete confirmation modal or popup",
        "standard portal header (user/role indicator, settings icon)",
    ],
    "generic": [
        "page title",
        "primary action button",
        "navigation element",
    ],
}


def get_expected_elements(screen_type: str) -> List[str]:
    """Return the expected element list for a screen type, falling back to generic."""
    return SCREEN_ELEMENT_TAXONOMY.get(screen_type, SCREEN_ELEMENT_TAXONOMY["generic"])
