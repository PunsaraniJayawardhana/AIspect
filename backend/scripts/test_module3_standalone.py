import argparse
import json
import sys

from backend.pipeline.module3.apfd_evaluator import (
    build_fault_map,
    random_apfd,
    run_ablation_study,
    severity_only_apfd,
)
from backend.pipeline.module3.cypress_runner import get_confirmed_faults, run_cypress_tests
from backend.pipeline.module3.docx_exporter import export_to_docx, export_to_markdown
from backend.pipeline.module3.fixture_loader import get_module1_inputs, get_module2_inputs
from backend.pipeline.module3.llm_client import get_usage_summary, reset_usage_log
from backend.pipeline.module3.test_generator import run_test_generator


def print_summary(story_key, app_url, tests):
    mode2 = [test for test in tests if test.get("mode") == "defect_first"]
    mode1 = [test for test in tests if test.get("mode") == "coverage_first"]
    print("==================================================")
    print(f"Running Module 3 standalone for: {story_key}")
    print(f"App URL: {app_url if app_url else 'None (Mode 2 skipped)'}")
    print("==================================================")
    print(f"Generated {len(tests)} test cases total")
    print(f"  Mode 2 (defect-first): {len(mode2)}")
    print(f"  Mode 1 (coverage-first): {len(mode1)}")
    print()

    if mode2:
        print("TPRI Rankings (Mode 2):")
        print("Rank   TC ID        TPRI     CI     ST     RC     FS     Scenario")
        print("-" * 84)
        for test in sorted(mode2, key=lambda item: item.get("priority_rank") or 999):
            print(
                f"{test.get('priority_rank', 0):>4}   {test.get('tc_id', ''):<10}   "
                f"{test.get('tpri_score', 0):>6.4f}   {test.get('ci', 0):>5.2f}   "
                f"{test.get('st', 0):>5.2f}   {test.get('rc', 0):>5.2f}   "
                f"{test.get('fs', 0):>5.2f}   {test.get('scenario', '')[:30]}"
            )

    usage = get_usage_summary()
    print("\nLLM Usage Summary:")
    print(f"  Calls: {usage['calls']}")
    print(f"  Prompt tokens: {usage['prompt_tokens']}")
    print(f"  Completion tokens: {usage['completion_tokens']}")
    print(f"  Total tokens: {usage['total_tokens']}")
    print(f"  Providers: {usage['by_provider']}")


def main():
    parser = argparse.ArgumentParser(description="Run Module 3 standalone for a story.")
    parser.add_argument("story_key")
    parser.add_argument("app_url", nargs="?", default=None)
    parser.add_argument("--ablation", action="store_true", help="Run APFD ablation study")
    args = parser.parse_args()

    reset_usage_log()

    explicit_acs, implicit_acs, story_text, nav_path = get_module1_inputs(
        args.story_key,
        [],
        [],
        "",
        "",
    )
    verified_discrepancies = get_module2_inputs(args.story_key, [])

    tests = run_test_generator(
        verified_discrepancies,
        explicit_acs,
        implicit_acs,
        story_text,
        args.story_key,
        app_url=args.app_url,
        nav_path=nav_path,
    )

    if args.app_url:
        tests = run_cypress_tests(tests)

    export_to_docx(tests, args.story_key, f"backend/scripts/fixtures/{args.story_key}_test_cases.docx")
    export_to_markdown(tests, args.story_key, f"backend/scripts/fixtures/{args.story_key}_test_cases.md")

    output_path = f"backend/scripts/fixtures/{args.story_key}_module3_output.json"
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump({"story_key": args.story_key, "tests": tests}, handle, indent=2)

    print_summary(args.story_key, args.app_url, tests)

    if args.app_url and args.ablation:
        mode2_tests = [test for test in tests if test.get("mode") == "defect_first"]
        if not mode2_tests:
            print("No defect-first tests were available for ablation study.")
            return 0

        fault_map = build_fault_map(mode2_tests)
        print("\nAPFD Results:")
        print(f"TPRI APFD: {run_ablation_study(verified_discrepancies, explicit_acs, story_text, mode2_tests, fault_map)['Full TPRI']['apfd']:.4f}")
        print(f"Random APFD: {random_apfd(mode2_tests, fault_map):.4f}")
        print(f"Severity-only APFD: {severity_only_apfd(mode2_tests, fault_map):.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
