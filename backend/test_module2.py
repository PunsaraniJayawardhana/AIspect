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
