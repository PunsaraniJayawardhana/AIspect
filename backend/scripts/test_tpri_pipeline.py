"""Load output/module2_output/<story>.json and run prioritize_discrepancies.
Run with: python -m backend.scripts.test_tpri_pipeline EXC-2
"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.pipeline.module3.tpri import prioritize_discrepancies


def main():
    story_key = sys.argv[1] if len(sys.argv) > 1 else "EXC-2"
    module2_path = os.path.join(ROOT, "output", "module2_output", f"{story_key}.json")

    with open(module2_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    discrepancies = payload.get("all_discrepancies", [])

    enriched_acs = [
        {"ac_id": "AC-01", "text": "The login page shall display an email input field"},
        {"ac_id": "AC-02", "text": "The login page shall have a password input"},
        {"ac_id": "AC-03", "text": "Users must be able to reset their password via email"},
        {"ac_id": "AC-04", "text": "Login button should be focusable and clickable"},
        {"ac_id": "AC-05", "text": "Form labels should align with inputs"},
    ]

    prioritized = prioritize_discrepancies(
        discrepancies,
        enriched_acs,
        "As a user, I want to log in so I can access my dashboard",
    )

    print(json.dumps(prioritized, indent=2))


if __name__ == "__main__":
    main()
