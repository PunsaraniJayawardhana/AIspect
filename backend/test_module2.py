"""
Manual Module 2 runner.

This script validates a single screen image against sample ACs and prints the
Module 2 confidence buckets. It is intentionally not an automated pytest test.

Usage:
    python -m backend.test_module2 --image test_screen.png
"""

import argparse
import base64
import json
import pathlib
import sys
import base64

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.pipeline.module2_validator import run_module2


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

from backend.pipeline.module2_validator import run_module2


def _load_image_b64(image_path: pathlib.Path) -> str:
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    return base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")


def build_sample_module1_output(image_b64: str) -> dict:
    return {
        "story_key": "PROJ-42",
        "story_text": (
            "As a customer I want to login with my email and password "
            "so that I can access my shopping account."
        ),
        "nav_path": "Home -> Login",
        "screen_type": "Authentication",
        "explicit_ACs": [
            "Email input field must be labeled Email",
            "Password input field must be labeled Password",
            "Login button must be labeled Login",
            "Forgot Password link must be visible",
        ],
        "implicit_ACs": [
            "Error message must appear for wrong credentials",
            "Remember Me checkbox should be available",
        ],
        "enriched_ACs": [
            "Email input field must be labeled Email",
            "Password input field must be labeled Password",
            "Login button must be labeled Login",
            "Forgot Password link must be visible",
            "Error message must appear for wrong credentials",
            "Remember Me checkbox should be available",
        ],
        "design_images_b64": [image_b64],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Module 2 with a local design image")
    parser.add_argument("--image", default="test_screen.png", help="Path to screenshot to validate")
    parser.add_argument("--output", default="module2_output.json", help="Where to save output JSON")
    args = parser.parse_args()

    image_path = pathlib.Path(args.image)
    try:
        img_b64 = _load_image_b64(image_path)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return 1

    print(f"Image loaded: {image_path}")
    module1_output = build_sample_module1_output(img_b64)
    result = run_module2(module1_output=module1_output)

    print("\nPASSED TO MODULE 3 (HIGH confidence):")
    print(json.dumps(result.get("high_confidence", []), indent=2))

    print("\nNEEDS HUMAN REVIEW (MEDIUM confidence):")
    print(json.dumps(result.get("medium_confidence", []), indent=2))

    print("\nDISCARDED (likely hallucinations):")
    print(json.dumps(result.get("low_confidence", []), indent=2))

    output_data = {
        "story_key": module1_output.get("story_key") or module1_output.get("ticket_id"),
        "total_runs": result.get("summary", {}).get("n_passes", 5),
        "summary": result.get("summary", {}),
        "passed_to_module3": result.get("high_confidence", []),
        "needs_human_review": result.get("medium_confidence", []),
        "discarded": result.get("low_confidence", []),
    }

    output_path = pathlib.Path(args.output)
    output_path.write_text(json.dumps(output_data, indent=2), encoding="utf-8")
    print(f"\nOutput saved to: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
