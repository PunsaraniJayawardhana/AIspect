# Validation prompts for Module 2 multi-pass validation
# Each prompt has slightly different phrasing
# but same semantic intent — to detect UI-requirement discrepancies

VALIDATION_PROMPTS = [
    "Analyze this UI design and identify all discrepancies against the given "
    "requirements. Only report issues visible in the DEFAULT static screen state. "
    "Do NOT flag error messages, validation messages, loading states, or any "
    "element that only appears after user interaction. Do NOT flag interaction "
    "behaviours such as routing, navigation outcomes, or authentication state "
    "changes — these cannot be evaluated from a static design image.",

    "Review this interface carefully and detect any mismatches between the UI "
    "design and the stated requirements. Report only elements that should be "
    "STATICALLY VISIBLE on the default screen. Do NOT report conditional states "
    "such as error messages or loading indicators. Do NOT report interaction "
    "behaviours such as where links navigate to, button click outcomes, or "
    "authentication-dependent rendering — these require a live application.",

    "Examine this UI screen and find elements that violate the stated acceptance "
    "criteria. Only report discrepancies visible in the static default view. "
    "Exclude any UI states that are triggered by user actions such as error "
    "messages, success messages, or validation feedback. Also exclude any "
    "routing or navigation behaviour and authentication state logic — "
    "these are not visible in a static design screenshot.",

    "Inspect this design against the requirements and list any inconsistencies "
    "in the STATIC DEFAULT STATE of the UI. Do NOT flag elements that are "
    "conditional — meaning elements that only appear after form submission, "
    "failed login, or any other user-triggered event. Do NOT flag interaction "
    "flows such as conditional rendering based on user authentication state, "
    "link routing destinations, or any behaviour requiring user interaction.",

    "Evaluate this UI design against the given requirements and report only "
    "discrepancies that are visible in the default static screen state. "
    "Ignore error states, validation messages, and any element that requires "
    "user interaction to appear. Also ignore all interaction behaviours — "
    "routing, navigation, authentication state changes, and conditional "
    "rendering logic — as these cannot be seen in a static image.",
]


def get_validation_prompt(run_number: int,
                          requirements: str) -> str:
    """
    Get prompt for a specific run number.
    Varies phrasing across runs while maintaining same semantic intent.
    """

    base = VALIDATION_PROMPTS[
        (run_number - 1) % len(VALIDATION_PROMPTS)
    ]

    taxonomy_list = """
- Missing Element: A required UI component is completely absent from the static design
- Wrong Label: Component exists but uses incorrect text or terminology
- Business Rule Violation: A business rule from requirements is not enforced in UI
- Layout Constraint Mismatch: Component placement violates layout requirements
- Interaction Flow Error: A user interaction flow is incorrectly represented
  in the STATIC design (e.g. wrong button placement, missing navigation element)
  NOTE: Do NOT use this for routing behaviour or authentication state logic
"""

    return f"""
{base}

REQUIREMENTS AND ACCEPTANCE CRITERIA:
{requirements}

DISCREPANCY TAXONOMY — classify each finding as exactly one of:
{taxonomy_list}

IMPORTANT RULES:
1. Only report discrepancies you can clearly see in the static UI image
2. Do not hallucinate or assume issues that are not visible
3. Be specific about the element name and what is wrong
4. Every discrepancy must map to a specific acceptance criterion
5. STATIC DESIGN RULE — This is a static screenshot of the DEFAULT screen
   state only. Do NOT flag the following as missing elements:
   - Error messages (only appear after failed actions)
   - Validation messages (only appear after form submission)
   - Success messages (only appear after successful actions)
   - Loading indicators (only appear during processing)
   - Warning alerts (only appear after specific user events)
   - Any element that requires user interaction to become visible
6. INTERACTION RULE — Do NOT flag interaction behaviours that cannot
   be seen in a static image:
   - Routing and navigation behaviour (where links or buttons go)
   - Authentication state changes (guest vs logged-in views)
   - Conditional rendering based on user state or session
   - Button click outcomes or form submission results
   - Any behaviour that requires clicking, tapping, or submitting
7. Only flag elements and properties that are DIRECTLY VISIBLE
   in the static design image right now with no interaction needed

Respond ONLY in this exact JSON format with no extra text:
{{
  "discrepancies": [
    {{
      "element_name": "exact name of the UI element",
      "discrepancy_type": "one type from taxonomy above",
      "acceptance_criterion_violated": "exact text of violated requirement",
      "description": "precise description of what is wrong",
      "natural_language_feedback": "clear human-readable explanation for the developer"
    }}
  ]
}}

If no discrepancies are found respond with:
{{"discrepancies": []}}
"""
