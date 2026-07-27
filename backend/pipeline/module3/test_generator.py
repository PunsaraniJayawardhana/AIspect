import json
import logging

from backend.pipeline.module3.fixture_loader import get_module1_inputs, get_module2_inputs
from backend.pipeline.module3.llm_client import call_llm
from backend.pipeline.module3.tpri import prioritize_discrepancies
from backend.pipeline.module3.input_schema import normalize_acs, adapt_discrepancies

logger = logging.getLogger(__name__)


def _normalize_acs(acs):
    normalized = []
    for idx, item in enumerate(acs or [], start=1):
        if isinstance(item, dict):
            normalized.append(
                {
                    "ac_id": item.get("ac_id") or f"AC-{idx:02d}",
                    "text": item.get("text") or item.get("ac_text") or "",
                    "type": item.get("type", "explicit"),
                }
            )
            continue

        normalized.append(
            {
                "ac_id": f"AC-{idx:02d}",
                "text": str(item),
                "type": "explicit",
            }
        )
    return normalized


def _clean_markdown(text):
    if not text:
        return ""

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 1)[1]
        if "\n" in cleaned:
            cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rstrip("`")
    return cleaned.strip()


def _parse_json_response(text, fallback):
    try:
        cleaned = _clean_markdown(text)
        parsed = json.loads(cleaned)
        return parsed
    except Exception:
        return fallback


def _priority_label(tpri_score):
    if tpri_score is None:
        return "Medium"
    if tpri_score >= 0.75:
        return "High"
    if tpri_score >= 0.5:
        return "Medium"
    return "Low"


def _mode1_fallback_rows(ac):
    return [
        {
            "scenario": f"Positive coverage for {ac['text']}",
            "type": "positive",
            "priority": "Medium",
            "steps": [
                "Open the relevant screen",
                f"Exercise the behavior described by {ac['ac_id']}",
                "Confirm the expected result is visible",
            ],
            "expected_result": f"The application satisfies {ac['text']}",
        },
        {
            "scenario": f"Negative coverage for {ac['text']}",
            "type": "negative",
            "priority": "Medium",
            "steps": [
                "Open the relevant screen",
                f"Trigger the invalid or missing condition for {ac['ac_id']}",
                "Confirm the application rejects or blocks the invalid path",
            ],
            "expected_result": f"The application handles the invalid path safely for {ac['text']}",
        },
        {
            "scenario": f"Boundary coverage for {ac['text']}",
            "type": "boundary",
            "priority": "Medium",
            "steps": [
                "Open the relevant screen",
                f"Apply the edge case for {ac['ac_id']}",
                "Confirm the boundary behavior is correct",
            ],
            "expected_result": f"Boundary behavior is correct for {ac['text']}",
        },
    ]


def _build_mode1_records(ac, ticket_id, generated_rows, start_index=1):
    records = []
    for idx, row in enumerate(generated_rows, start=start_index):
        records.append(
            {
                "tc_id": f"TC-M1-{idx:03d}",
                "mode": "coverage_first",
                "ticket_id": ticket_id,
                "ac_id": ac["ac_id"],
                "discrepancy_id": None,
                "requirement_id": None,
                "scenario": row.get("scenario", f"Coverage for {ac['text']}"),
                "priority": row.get("priority", "Medium"),
                "steps": row.get("steps", []),
                "expected_result": row.get("expected_result", f"Coverage for {ac['text']}"),
                "tpri_score": None,
                "priority_rank": None,
                "ci": None,
                "st": None,
                "rc": None,
                "rc_reasoning": None,
                "fs": None,
                "cypress_script": None,
                "passed": None,
                "confirmed_fault": None,
                "jira_ticket": None,
            }
        )
    return records


def _mode2_fallback(discrepancy, ticket_id, app_url):
    summary = discrepancy.get("description") or discrepancy.get("ac_text") or "reported discrepancy"
    script = (
        f"describe('Defect check: {summary}', () => {{\n"
        f"  it('Validates the live application against the reported discrepancy', () => {{\n"
        f"    cy.visit('{app_url}');\n"
        f"    cy.contains('body', '{summary}', {{ timeout: 10000 }}).should('not.exist');\n"
        "  }});\n"
        "}});\n"
    )

    return {
        "tc_id": f"TC-M2-{discrepancy.get('priority_rank', 1):03d}",
        "mode": "defect_first",
        "ticket_id": ticket_id,
        "ac_id": discrepancy.get("requirement_id") or discrepancy.get("ac_id") or "AC-01",
        "discrepancy_id": discrepancy.get("discrepancy_id"),
        "requirement_id": discrepancy.get("requirement_id"),
        "scenario": f"Verify the live application against {discrepancy.get('ac_text', 'the reported discrepancy')}",
        "priority": _priority_label(discrepancy.get("tpri_score")),
        "steps": [
            "Open the application URL",
            "Navigate to the relevant screen",
            "Check whether the reported discrepancy is present in the live UI",
        ],
        "expected_result": discrepancy.get("description") or "The discrepancy should be detectable in the live application",
        "tpri_score": discrepancy.get("tpri_score"),
        "priority_rank": discrepancy.get("priority_rank"),
        "ci": discrepancy.get("ci"),
        "st": discrepancy.get("st"),
        "rc": discrepancy.get("rc"),
        "rc_reasoning": discrepancy.get("rc_reasoning"),
        "fs": discrepancy.get("fs"),
        "cypress_script": script,
        "passed": None,
        "confirmed_fault": None,
        "jira_ticket": None,
    }


def generate_coverage_tests(enriched_acs, user_story, ticket_id):
    normalized = _normalize_acs(enriched_acs)
    tests = []
    counter = 1

    for ac in normalized:
        prompt = (
            "You are a QA engineer writing test cases.\n\n"
            f"User Story: {user_story}\n"
            f"Acceptance Criterion ({ac['ac_id']}): {ac['text']}\n\n"
            "Generate test cases covering:\n"
            "1. One POSITIVE test (valid, happy-path scenario)\n"
            "2. One NEGATIVE test (invalid input or missing element)\n"
            "3. One BOUNDARY test where applicable\n\n"
            "Respond ONLY as a JSON array, no markdown fences:\n"
            "[\n"
            "  {\n"
            '    "scenario": "short description of what is tested",\n'
            '    "type": "positive | negative | boundary",\n'
            '    "priority": "High | Medium | Low",\n'
            '    "steps": ["step 1", "step 2", "step 3"],\n'
            '    "expected_result": "what should happen"\n'
            "  }\n"
            "]"
        )

        try:
            response = call_llm(prompt)
            parsed = _parse_json_response(response, [])
            if not isinstance(parsed, list):
                raise ValueError("LLM response was not a JSON array")
            generated = _build_mode1_records(ac, ticket_id, parsed, start_index=counter)
            tests.extend(generated)
            counter += len(generated)
        except Exception as exc:
            logger.warning("Coverage test generation failed for %s: %s", ac["ac_id"], exc)
            generated = _build_mode1_records(ac, ticket_id, _mode1_fallback_rows(ac), start_index=counter)
            tests.extend(generated)
            counter += len(generated)

    return tests


def generate_defect_tests(prioritized_discrepancies, app_url, ticket_id):
    tests = []

    for discrepancy in prioritized_discrepancies or []:
        prompt = (
            "You are a Cypress test automation engineer.\n\n"
            f"Application URL: {app_url}\n"
            f"Discrepancy Type: {discrepancy.get('discrepancy_type', 'Unknown')}\n"
            f"Description: {discrepancy.get('description', '')}\n"
            f"UI Location: {discrepancy.get('location', 'Unknown')}\n"
            f"Violated AC: {discrepancy.get('ac_text', discrepancy.get('requirement_id', ''))}\n"
            f"TPRI Score: {discrepancy.get('tpri_score', 0.0)} | Rank: {discrepancy.get('priority_rank', 1)}\n\n"
            "Write a complete Cypress test that navigates to the page and asserts\n"
            "whether the described discrepancy exists in the live application.\n"
            "Selector preference: data-testid > aria-label > visible text.\n\n"
            "Respond with raw JavaScript only. No markdown. Start with: describe("
        )

        try:
            response = call_llm(prompt)
            script = _clean_markdown(response)
            if not script.startswith("describe("):
                raise ValueError("LLM response did not contain a Cypress script")
            test = _mode2_fallback(discrepancy, ticket_id, app_url)
            test["cypress_script"] = script
            tests.append(test)
        except Exception as exc:
            logger.warning("Defect test generation failed for %s: %s", discrepancy.get("discrepancy_id"), exc)
            tests.append(_mode2_fallback(discrepancy, ticket_id, app_url))

    return tests


def run_test_generator(
    verified_discrepancies,
    explicit_acs,
    implicit_acs,
    story_text,
    story_key,
    app_url=None,
    nav_path="",
):
    explicit_acs, implicit_acs, story_text, nav_path = get_module1_inputs(
        story_key,
        explicit_acs,
        implicit_acs,
        story_text,
        nav_path,
    )
    verified_discrepancies = get_module2_inputs(story_key, verified_discrepancies)

    normalized_explicit = normalize_acs(explicit_acs, default_type="explicit", start_index=1)
    normalized_implicit = normalize_acs(
        implicit_acs, default_type="implicit", start_index=len(normalized_explicit) + 1
    )
    all_acs = normalized_explicit + normalized_implicit
    
    adapted_discrepancies = adapt_discrepancies(verified_discrepancies, all_acs)

    prioritized = prioritize_discrepancies(
        adapted_discrepancies,
        all_acs,
        story_text or "Unknown user story",
    )

    for item in adapted_discrepancies:
        print(f"[Module3 DEBUG] requirement_id={item.get('requirement_id')} "
              f"ac_match_score={item.get('ac_match_score')} "
              f"ac_text={item.get('ac_text')[:60]}")

    defect_tests = generate_defect_tests(prioritized, app_url, story_key) if app_url else []
    coverage_tests = generate_coverage_tests(all_acs, story_text or "Unknown user story", story_key)

    return defect_tests + coverage_tests
