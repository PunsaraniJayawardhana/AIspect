# Validation prompts for Module 2 multi-pass validation
# Each prompt has slightly different phrasing
# but same semantic intent — to detect UI-requirement discrepancies

VALIDATION_PROMPTS = [
    "Analyze this UI design and identify all discrepancies against the given requirements. Be precise and only report genuine issues you can clearly see.",
    "Review this interface carefully and detect any mismatches between the UI design and the stated requirements. Report only real and visible issues.",
    "Examine this UI screen and find elements that violate the stated acceptance criteria. Only report discrepancies that are clearly present.",
    "Inspect this design against the requirements and list any inconsistencies you can clearly identify in the UI components.",
    "Evaluate this UI design against the given requirements and report only discrepancies that genuinely exist in the design."
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
- Missing Element: A required UI component is completely absent
- Wrong Label: Component exists but uses incorrect text or terminology
- Business Rule Violation: A business rule from requirements is not enforced in UI
- Layout Constraint Mismatch: Component placement violates layout requirements
- Interaction Flow Error: User interaction flow violates requirements
"""

    return f"""
{base}

REQUIREMENTS AND ACCEPTANCE CRITERIA:
{requirements}

DISCREPANCY TAXONOMY — classify each finding as exactly one of:
{taxonomy_list}

IMPORTANT RULES:
1. Only report discrepancies you can clearly see in the UI image
2. Do not hallucinate or assume issues that are not visible
3. Be specific about the element name and what is wrong
4. Every discrepancy must map to a specific acceptance criterion

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