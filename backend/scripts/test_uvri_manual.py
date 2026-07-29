"""
Manual sanity-check script for the UVRI sub-metrics, using hand-crafted
acceptance-criteria sets instead of a live Jira ticket. Useful for isolating
UVRI logic bugs from ADF-parsing/Jira-connectivity issues, and for a quick
regression check any time coverage_density.py, assertion_specificity.py,
ambiguity_penalty.py, testability_score.py, or uvri.py are modified.

Run with:
    python -m backend.scripts.test_uvri_manual
"""

import asyncio
from pipeline.module1.uvri import compute_uvri
from pipeline.module1.ambiguity_penalty import compute_ambiguity_penalty


# ── Case 1: LOGIN screen ────────────────────────────────────────────────

GOOD_LOGIN_ACS = [
    "The email field shall be visible and accept a valid email address.",
    "The password field shall mask input characters by default.",
    "The password field shall include a show/hide toggle icon.",
    "The login button shall be disabled until both fields are filled.",
    "A 'Forgot password?' link shall be displayed below the password field.",
    "On successful login, the user shall be navigated to /dashboard.",
    "The page shall display the application logo at the top.",
]

POOR_LOGIN_ACS = [
    "The screen should look appropriate for a login page.",
    "The user should be able to log in easily.",
]

# ── Case 2: SIGNUP screen (mirrors the real EXC-1 story used in live testing) ──

GOOD_SIGNUP_ACS = [
    "The name field is required and displays 'Name is required' if left empty.",
    "The email field validates for a proper email format before submission.",
    "The password field masks input and displays 'Password is required' if empty.",
    "The confirm password field must match the password field exactly.",
    "The create account button validates all fields and redirects to /home on success.",
    "The sign up screen displays a 'Sign up with Google' button that initiates OAuth.",
    "The sign up screen displays a 'Log in' link at the bottom for existing users.",
]

POOR_SIGNUP_ACS = [
    "Users can register on this page.",
    "The form should be user-friendly and easy to fill out.",
]

# ── Edge case: empty AC list ─────────────────────────────────────────────

EMPTY_ACS = []


async def run_case(label: str, acs: list, screen_type: str):
    print(f"\n{'='*60}\n{label}  (screen_type={screen_type})\n{'='*60}")
    print(f"ACs ({len(acs)}):")
    for ac in acs:
        print(f"  - {ac}")

    uvri, sub = await compute_uvri(acs, screen_type)

    print(f"\nUVRI = {uvri:.4f}")
    print(f"  coverage     = {sub['coverage']:.4f}")
    print(f"  specificity  = {sub['specificity']:.4f}")
    print(f"  ambiguity    = {sub['ambiguity']:.4f}")
    print(f"  testability  = {sub['testability']:.4f}")

    cov = sub["details"]["coverage"]
    print(f"\n  Coverage — missing elements ({len(cov['missing_elements'])}):")
    for el in cov["missing_elements"]:
        print(f"    - {el}")

    amb = sub["details"]["ambiguity"]
    print(f"\n  Ambiguity — matched terms ({amb['ambiguous_count']} / {amb['total_words']} words):")
    for m in amb["matched_terms"]:
        print(f"    - '{m['term']}' [{m['category']}]")

    spec = sub["details"]["specificity"]
    print(f"\n  Specificity — per-AC breakdown:")
    for entry in spec["per_ac"]:
        print(f"    - score={entry['score']:.2f}  checks={entry['checks']}  ac='{entry['ac'][:60]}'")

    test = sub["details"]["testability"]
    print(f"\n  Testability — per-AC breakdown:")
    for entry in test["per_ac"]:
        print(f"    - testable={entry['testable']}  ac='{entry['ac'][:60]}'")

    return uvri, sub


def run_ambiguity_only_sync_check():
    """Quick check that needs NO API key — pure regex, instant feedback."""
    print(f"\n{'='*60}\nSYNC-ONLY ambiguity_penalty check (no LLM, no API key needed)\n{'='*60}")
    cases = [
        ("GOOD login", GOOD_LOGIN_ACS),
        ("POOR login", POOR_LOGIN_ACS),
        ("GOOD signup", GOOD_SIGNUP_ACS),
        ("POOR signup", POOR_SIGNUP_ACS),
        ("EMPTY", EMPTY_ACS),
    ]
    for label, acs in cases:
        score, details = compute_ambiguity_penalty(acs)
        terms = [m["term"] for m in details["matched_terms"]]
        print(f"  {label}: ambiguity={score:.4f}  matched={terms}")


async def main():
    run_ambiguity_only_sync_check()

    good_login_uvri, _ = await run_case("GOOD login story", GOOD_LOGIN_ACS, "login")
    poor_login_uvri, _ = await run_case("POOR login story", POOR_LOGIN_ACS, "login")

    good_signup_uvri, _ = await run_case("GOOD signup story", GOOD_SIGNUP_ACS, "signup")
    poor_signup_uvri, _ = await run_case("POOR signup story", POOR_SIGNUP_ACS, "signup")

    empty_uvri, _ = await run_case("EMPTY ACs", EMPTY_ACS, "login")

    print(f"\n{'='*60}\nSUMMARY\n{'='*60}")
    print(f"GOOD login  UVRI = {good_login_uvri:.4f}")
    print(f"POOR login  UVRI = {poor_login_uvri:.4f}")
    print(f"GOOD signup UVRI = {good_signup_uvri:.4f}")
    print(f"POOR signup UVRI = {poor_signup_uvri:.4f}")
    print(f"EMPTY       UVRI = {empty_uvri:.4f}")

    assert good_login_uvri > poor_login_uvri, "FAIL: good login should score higher than poor login"
    assert good_signup_uvri > poor_signup_uvri, "FAIL: good signup should score higher than poor signup"
    assert poor_login_uvri >= empty_uvri, "FAIL: poor login should score at least as high as empty"
    print("\nSanity checks PASSED: good > poor >= empty, across both screen types")


if __name__ == "__main__":
    asyncio.run(main())
