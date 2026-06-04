# backend/pipeline/module2/validation_prompts.py

SYSTEM_PROMPT = """You are a senior QA engineer performing a semantic design audit.
You will be given a set of acceptance criteria and one or more UI design images.
Your task is to identify discrepancies between the acceptance criteria and what is 
visually present in the design.

You MUST respond ONLY with a valid JSON array. No preamble, no explanation, no markdown.
Each object in the array must have exactly these keys:
- "element_name": string — the specific UI element involved
- "discrepancy_type": one of ["Missing Element", "Wrong Label", "Business Rule Violation", 
  "Layout Constraint Mismatch", "Interaction Flow Error"]
- "violated_criterion": string — the exact acceptance criterion text being violated
- "screen_region": string — where on the screen (e.g. "top navigation", "form body", "footer")
- "description": string — one sentence describing the discrepancy

If no discrepancies are found, return an empty array: []
"""

# 5 prompt variations — same intent, different phrasing
VALIDATION_PROMPT_VARIANTS = [
    # Variant 1 — direct audit framing
    """Review the acceptance criteria below and examine the design image(s).
List every discrepancy where the design fails to satisfy a criterion.

Acceptance Criteria:
{criteria}

Respond with a JSON array only.""",

    # Variant 2 — checklist framing
    """For each acceptance criterion listed, check whether the design image satisfies it.
Report any criterion that is not fully satisfied as a discrepancy.

Acceptance Criteria:
{criteria}

Return a JSON array of discrepancies only.""",

    # Variant 3 — QA tester perspective
    """Imagine you are a QA tester comparing a written specification against a UI mockup.
Identify every case where the mockup does not match the specification below.

Specification (Acceptance Criteria):
{criteria}

Output: JSON array.""",

    # Variant 4 — gap analysis framing
    """Perform a gap analysis between the following requirements and the UI design.
A gap exists when a required element is absent, mislabelled, or incorrectly positioned.

Requirements:
{criteria}

Respond with only a JSON array of gaps found.""",

    # Variant 5 — defect hunting framing
    """Hunt for defects in the UI design relative to the requirements below.
A defect is any visual element that contradicts, omits, or misrepresents a requirement.

Requirements:
{criteria}

Return your findings as a JSON array only.""",
]