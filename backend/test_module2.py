"""
Test Module 2 using simulated Module 1 output.
Replace simulated data with real Module 1 output
when connecting the full pipeline.
"""

import json
import os
import sys
import base64

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline.module2_validator import run_module2


# ── Load Figma Image ──────────────────────────────────────────
image_path = "test_screen.png"

if not os.path.exists(image_path):
    print(f"ERROR: Place your Figma screen at: {image_path}")
    exit()

with open(image_path, "rb") as f:
    img_b64 = base64.standard_b64encode(
        f.read()
    ).decode("utf-8")

print(f"Image loaded: {image_path}")


# ── Simulated Module 1 Output ─────────────────────────────────
# Replace this with real Module 1 output when ready
module1_output = {
    "story_key": "PROJ-42",

    "story_text": """As a customer I want to login 
    with my email and password so that I can 
    access my shopping account.""",

    "nav_path": "Home → Login",

    "screen_type": "Authentication",

    "explicit_ACs": [
        "Email input field must be labeled Email",
        "Password input field must be labeled Password",
        "Login button must be labeled Login",
        "Forgot Password link must be visible"
    ],

    "implicit_ACs": [
        "Error message must appear for wrong credentials",
        "Remember Me checkbox should be available"
    ],

    "enriched_ACs": [
        "Email input field must be labeled Email",
        "Password input field must be labeled Password",
        "Login button must be labeled Login",
        "Forgot Password link must be visible",
        "Error message must appear for wrong credentials",
        "Remember Me checkbox should be available"
    ],

    # Raw base64 image from Figma
    # Module 1 will fill this automatically
    "design_images_b64": [img_b64]
}


# ── Run Module 2 ──────────────────────────────────────────────
result = run_module2(
    module1_output=module1_output,
    N=5
)


# ── Print Results ─────────────────────────────────────────────
print("\n\nPASSED TO MODULE 3 (HIGH confidence):")
print(json.dumps(result.passed_to_module3, indent=2))

print("\n\nNEEDS HUMAN REVIEW (MEDIUM confidence):")
print(json.dumps(result.needs_human_review, indent=2))

print("\n\nDISCARDED (likely hallucinations):")
print(json.dumps(result.discarded, indent=2))


# ── Save Output JSON ──────────────────────────────────────────
output_data = {
    "story_key": module1_output["story_key"],
    "total_runs": result.total_runs,
    "summary": result.summary(),
    "passed_to_module3": result.passed_to_module3,
    "needs_human_review": result.needs_human_review,
    "discarded": result.discarded
}

with open("module2_output.json", "w") as f:
    json.dump(output_data, f, indent=2)

print("\n\nOutput saved to: module2_output.json")
