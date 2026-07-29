"""
System/user prompt builders for the three LLM-dependent UVRI sub-terms:
Coverage Density (element matching), Assertion Specificity (4 binary
checks), and Testability (pass/fail judgement). Ambiguity Penalty is
excluded — it's pure lexicon matching with no LLM call.

Each builder takes the whole AC list for a story and returns ONE prompt,
so each sub-term costs one API call per story rather than one per AC.
"""

from typing import List


# ── Coverage Density ────────────────────────────────────────────────────

COVERAGE_SYSTEM_PROMPT = """You audit acceptance criteria for a UI screen against a fixed reference list of expected UI elements for that screen type.

Your task: for EACH element in the reference list, decide whether it is EXPLICITLY referenced (named or clearly described) in the acceptance criteria provided.

Rules:
- Only mark an element as referenced if the acceptance criteria explicitly name it or unambiguously describe it. Do not infer elements that are merely plausible.
- Do not consider anything outside the given acceptance criteria text.

Return ONLY a valid JSON array, one object per reference element, each with:
- "element": the exact reference element name as given
- "referenced": true or false

Do not include explanation, preamble, or Markdown code fences."""


def build_coverage_user_prompt(acs: List[str], expected_elements: List[str]) -> str:
    ac_block = "\n".join(f"  - {ac}" for ac in acs) or "  (none)"
    ref_block = "\n".join(f"  - {el}" for el in expected_elements)
    return f"""REFERENCE ELEMENT LIST (this screen type's expected UI elements):
{ref_block}

ACCEPTANCE CRITERIA:
{ac_block}

For each reference element, determine if it is explicitly referenced in the acceptance criteria above. Return only the JSON array as specified."""


# ── Assertion Specificity ───────────────────────────────────────────────

SPECIFICITY_SYSTEM_PROMPT = """You evaluate the testability of acceptance criteria (ACs) using four independent binary checks. For EACH acceptance criterion given, answer each check with true or false:

1. names_element: Does the AC name a specific, identifiable UI element (not a vague reference like "the screen" or "it")?
2. observable_state: Does the AC specify an observable state or behaviour (e.g. visible, disabled, masked) rather than a vague quality (e.g. "works", "looks correct")?
3. concrete_value: Does the AC include a concrete value, constraint, or limit (e.g. a character limit, a specific label text, a specific URL)?
4. measurable_outcome: Does the AC specify a measurable, checkable outcome (e.g. a specific navigation target, a specific displayed message) rather than a vague result (e.g. "the user proceeds")?

Return ONLY a valid JSON array, one object per acceptance criterion, each with:
- "ac": the acceptance criterion text (verbatim, truncate to first 80 characters if longer)
- "names_element": true/false
- "observable_state": true/false
- "concrete_value": true/false
- "measurable_outcome": true/false

Do not include explanation, preamble, or Markdown code fences."""


def build_specificity_user_prompt(acs: List[str]) -> str:
    ac_block = "\n".join(f"  {i+1}. {ac}" for i, ac in enumerate(acs)) or "  (none)"
    return f"""ACCEPTANCE CRITERIA:
{ac_block}

Evaluate each acceptance criterion against the four checks. Return only the JSON array as specified."""


# ── Testability ──────────────────────────────────────────────────────────

TESTABILITY_SYSTEM_PROMPT = """You evaluate whether acceptance criteria (ACs) can be directly converted into a single Cypress assertion of the form cy.get(...).should(...).

For EACH acceptance criterion given, judge whether it describes a single, concrete, checkable UI condition that a Cypress test could assert against directly, without requiring further clarification or additional context.

Return ONLY a valid JSON array, one object per acceptance criterion, each with:
- "ac": the acceptance criterion text (verbatim, truncate to first 80 characters if longer)
- "testable": true or false

Do not include explanation, preamble, or Markdown code fences."""


def build_testability_user_prompt(acs: List[str]) -> str:
    ac_block = "\n".join(f"  {i+1}. {ac}" for i, ac in enumerate(acs)) or "  (none)"
    return f"""ACCEPTANCE CRITERIA:
{ac_block}

Judge the testability of each acceptance criterion. Return only the JSON array as specified."""
