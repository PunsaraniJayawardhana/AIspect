import json
import os
import pathlib
import httpx
from backend.jobs.job_store import Job
from backend.integrations.jira_client import (
    fetch_single_story,
    fetch_attachment_as_base64,
    create_bug_ticket,
)

from backend.pipeline.module1.adf_parser import parse_adf
from backend.pipeline.module1.screen_classifier import classify_screen_type
from backend.pipeline.module1.uvri import compute_uvri
from backend.pipeline.module1.inference import infer_implicit_elements
from backend.pipeline.module2.multipass_validator import run_multipass_validation
from backend.pipeline.module2.confidence_index import compute_confidence_index
from backend.pipeline.module3.test_generator import generate_dual_mode_tests
from backend.pipeline.module3.cypress_runner import execute_cypress


RESULTS_DIR        = pathlib.Path("output/results")
MODULE2_OUTPUT_DIR = pathlib.Path("output/module2_output")

# Keywords that indicate dynamic/conditional behaviour
# ACs containing these cannot be validated from a static design image
DYNAMIC_AC_KEYWORDS = [
    "on submit", "on click", "after submit", "on valid",
    "on invalid", "on success", "on error", "on empty",
    "when user", "after user", "displays an error",
    "shows a success", "shows confirmation", "shows message",
    "displays a message", "displays an inline",
    "redirects", "navigates to", "routes to",
    "if authenticated", "if guest", "if the user is",
    "opens in a new tab", "target=", "target=\"_blank\"",
    "mailto:", "tel:", "clickable mailto", "clickable tel",
    "sourced from", "central configuration", "cms",
    "global component", "rendered on all pages",
    "responsive", "stack vertically", "hover state",
    "open in a new tab", "new tab",
]


def classify_acs(enriched_ACs: list) -> tuple:
    """
    Separate enriched ACs into two categories:
    - static_ACs: validatable from a static design image
    - dynamic_ACs: require live application testing (Module 3)

    Returns (static_ACs, dynamic_ACs)
    """
    static_ACs = []
    dynamic_ACs = []

    for ac in enriched_ACs:
        ac_lower = ac.lower()
        is_dynamic = any(
            keyword in ac_lower
            for keyword in DYNAMIC_AC_KEYWORDS
        )
        if is_dynamic:
            dynamic_ACs.append(ac)
            print(f"[AC Classifier] DYNAMIC (skipped for Module 2): "
                  f"{ac[:80]}...")
        else:
            static_ACs.append(ac)

    print(f"\n[AC Classifier] Total ACs: {len(enriched_ACs)}")
    print(f"[AC Classifier] Static  (→ Module 2): {len(static_ACs)}")
    print(f"[AC Classifier] Dynamic (→ Module 3): {len(dynamic_ACs)}\n")

    return static_ACs, dynamic_ACs


async def emit(job: Job, step: str, payload: dict = None):
    """Push a progress event to the job's stream."""
    job.current_step = step
    await job.event_queue.put({"step": step, "payload": payload or {}})


def _persist_result(story_key: str, result: dict) -> None:
    """Write the final pipeline result to disk."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{story_key}.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _persist_module2_output(story_key: str, result: dict) -> None:
    """Save Module 2 output as a dedicated file for Module 3 consumption."""
    MODULE2_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (MODULE2_OUTPUT_DIR / f"{story_key}.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


async def process_one_story(job: Job, story_key: str, app_url: str = None, nav_path_override: str = ""):
    try:
        job.status = "running"

        # ── Read N from environment variable ────────────────────────
        n_passes = int(os.environ.get("MODULE2_PASSES", 5))
        print(f"[Module2] N passes set to: {n_passes}")

        # ── 1. Fetch the ticket ──────────────────────────────────
        await emit(job, "fetching_ticket")
        story = await fetch_single_story(story_key)

        # Skip tickets with no description
        if story["description_adf"] is None:
            skip_record = {
                "story_key":      story_key,
                "story_summary":  story.get("summary", ""),
                "status_at_skip": story.get("status"),
                "skipped":        True,
                "reason":         "null description",
            }
            _persist_result(story_key, skip_record)
            job.status = "completed"
            job.result = skip_record
            await emit(job, "done", job.result)
            return

        # ── 2. Parse the ADF tree ────────────────────────────────
        await emit(job, "parsing_adf")
        parsed = parse_adf(story["description_adf"])
        story_text = parsed.get("story_text", "")
        nav_path = parsed.get("nav_path", "")
        if nav_path_override:
            nav_path = nav_path_override

        # ── 3. Download design images ────────────────────────────
        image_attachments = [
            a for a in story["attachments"]
            if a.get("mime_type", "").startswith("image/")
        ]
        await emit(job, "downloading_design_images", {"count": len(image_attachments)})
        design_images_b64 = []
        for attachment in image_attachments:
            img = await fetch_attachment_as_base64(attachment["content_url"])
            design_images_b64.append(img)

        # ── 4. Module 1 — Screen classification ──────────────────
        await emit(job, "classifying_screen_type")
        screen_type = await classify_screen_type(parsed)
        await emit(job, "screen_type_classified", {"screen_type": screen_type})

        # ── 5. Module 1 — UVRI pre-enrichment ────────────────────
        await emit(job, "computing_uvri_pre")
        uvri_pre, sub_pre = await compute_uvri(parsed["explicit_ACs"], screen_type)
        await emit(job, "uvri_pre_done", {"uvri": uvri_pre, "subterms": sub_pre})

        # ── 6. Module 1 — Implicit inference ─────────────────────
        await emit(job, "running_implicit_inference")
        implicit_ACs = await infer_implicit_elements(parsed, screen_type)
        await emit(job, "inference_done", {"implicit_ACs": implicit_ACs})

        explicit_ACs = parsed["explicit_ACs"]
        enriched_ACs = explicit_ACs + implicit_ACs
        canonical_acs = [
            {
                "ac_id": f"AC-{idx:02d}",
                "text": ac,
                "type": "explicit" if idx <= len(explicit_ACs) else "implicit",
            }
            for idx, ac in enumerate(enriched_ACs, start=1)
        ]

        # ── 7. Module 1 — UVRI post-enrichment ───────────────────
        await emit(job, "computing_uvri_post")
        uvri_post, sub_post = await compute_uvri(enriched_ACs, screen_type)
        await emit(job, "uvri_post_done", {
            "uvri":     uvri_post,
            "subterms": sub_post,
            "delta":    uvri_post - uvri_pre,
        })

        # ── 7.5 — AC Pre-Classification ──────────────────────────
        await emit(job, "classifying_acs")
        static_ACs, dynamic_ACs = classify_acs(enriched_ACs)
        await emit(job, "acs_classified", {
            "static_count":  len(static_ACs),
            "dynamic_count": len(dynamic_ACs),
        })

        # ── 8. Module 2 — Multi-pass validation ─────────────────────
        # Only static ACs are sent to Module 2
        # Dynamic ACs bypass Module 2 and go directly to Module 3
        await emit(job, "module2_started", {"total_passes": n_passes})
        passes = await run_multipass_validation(
            static_ACs,
            design_images_b64,
            n=n_passes
        )
        await emit(job, "module2_passes_complete")

        verified = compute_confidence_index(
            passes,
            n_passes=n_passes,
            canonical_acs=canonical_acs,
        )

        # Split by confidence level
        high_confidence = [
            d for d in verified if d["confidence_label"] == "HIGH"
        ]
        medium_confidence = [
            d for d in verified if d["confidence_label"] == "MEDIUM"
        ]
        low_confidence = [
            d for d in verified if d["confidence_label"] == "LOW"
        ]

        print(f"[Module2] HIGH: {len(high_confidence)}, "
              f"MEDIUM: {len(medium_confidence)}, "
              f"LOW (discarded): {len(low_confidence)}")

        # Save dedicated Module 3 input file
        module2_output = {
            "ticket_id":    story_key,
            "screen_type":  screen_type,
            "high_confidence":   high_confidence,
            "medium_confidence": medium_confidence,
            "all_discrepancies": verified,
            "dynamic_ACs":       dynamic_ACs,
            "summary": {
                "total_candidates":      len(verified),
                "high":                  len(high_confidence),
                "medium":                len(medium_confidence),
                "low":                   len(low_confidence),
                "n_passes":              n_passes,
                "static_acs_validated":  len(static_ACs),
                "dynamic_acs_deferred":  len(dynamic_ACs),
            }
        }
        _persist_module2_output(story_key, module2_output)
        print(f"[Module2] Module 3 input saved to "
              f"output/module2_output/{story_key}.json")

        await emit(job, "module2_done", {"verified_discrepancies": verified})

        # ── 9. Module 3 — Test generation ───────────────────────────
        await emit(job, "generating_tests")
        tests = generate_dual_mode_tests(
            verified,
            explicit_ACs,
            implicit_ACs,
            story_text,
            story_key,
            screen_type=screen_type,
            app_url=app_url,
            nav_path=nav_path,
        )

        docx_path = export_to_docx(tests, story_key, f"output/module3/{story_key}_test_cases.docx")
        markdown_path = export_to_markdown(tests, story_key, f"output/module3/{story_key}_test_cases.md")
        await emit(job, "tests_generated", {"test_count": len(tests)})

        # ── 10. Module 3 — Cypress execution ────────────────────────
        cypress_results = []
        bugs_created = []
        if app_url:
            defect_only_mode = str(os.environ.get("MODULE3_DEFECT_ONLY", "")).strip().lower() in {"1", "true", "yes", "on"}
            await emit(job, "running_cypress", {
                "execution_mode": "defect_only" if defect_only_mode else "ticket_level",
                "execution_mode_source": "MODULE3_DEFECT_ONLY" if defect_only_mode else "default",
                "test_breakdown": {
                    "defect_first": {
                        "generated": sum(1 for test in tests if test.get("mode") == "defect_first"),
                    },
                    "coverage_first": {
                        "generated": sum(1 for test in tests if test.get("mode") == "coverage_first"),
                    },
                }
            })
            cypress_results = await execute_cypress(tests, app_url, defects_only=defect_only_mode)
            await emit(job, "cypress_done", {
                "results": cypress_results,
                "execution_mode": "defect_only" if defect_only_mode else "ticket_level",
                "execution_mode_source": "MODULE3_DEFECT_ONLY" if defect_only_mode else "default",
                "test_breakdown": {
                    "defect_first": {
                        "executed": sum(1 for result in cypress_results if result.get("mode") == "defect_first"),
                        "passed": sum(1 for result in cypress_results if result.get("mode") == "defect_first" and result.get("passed") is True),
                        "failed": sum(1 for result in cypress_results if result.get("mode") == "defect_first" and result.get("confirmed_fault") is True),
                        "skipped": sum(1 for result in cypress_results if result.get("mode") == "defect_first" and result.get("passed") is None),
                    },
                    "coverage_first": {
                        "executed": sum(1 for result in cypress_results if result.get("mode") == "coverage_first"),
                        "passed": sum(1 for result in cypress_results if result.get("mode") == "coverage_first" and result.get("passed") is True),
                        "failed": sum(1 for result in cypress_results if result.get("mode") == "coverage_first" and result.get("confirmed_fault") is True),
                        "skipped": sum(1 for result in cypress_results if result.get("mode") == "coverage_first" and result.get("passed") is None),
                    },
                },
            })

            cypress_object_ids = {id(item) for item in cypress_results}

            def _matches_record(record: dict, discrepancy_id: str, tc_id: str) -> bool:
                if discrepancy_id and record.get("discrepancy_id") == discrepancy_id:
                    return True
                if tc_id and record.get("tc_id") == tc_id:
                    return True
                return False

            def _set_ticket(records, ticket_key: str, discrepancy_id: str, tc_id: str, skip_shared: bool = False):
                for record in records or []:
                    if skip_shared and id(record) in cypress_object_ids:
                        continue
                    if _matches_record(record, discrepancy_id, tc_id):
                        record["jira_ticket"] = ticket_key

            for result in get_confirmed_faults(cypress_results):
                await emit(job, "creating_bug_ticket", {"discrepancy": result.get("discrepancy_id")})
                bug = await create_bug_ticket(
                    summary=f"[AIspect] {result.get('scenario', result.get('discrepancy_id'))}",
                    description=(
                        f"{result.get('expected_result', '')} | "
                        f"{result.get('scenario', '')}"
                    ).strip(" |"),
                    parent_story_key=story_key,
                    severity=result.get("priority", "Medium"),
                )
                bugs_created.append(
                    {
                        "ticket_key": bug["key"],
                        "discrepancy_id": result.get("discrepancy_id"),
                    }
                )

                ticket_key = bug["key"]
                discrepancy_id = result.get("discrepancy_id")
                tc_id = result.get("tc_id")

                _set_ticket(tests, ticket_key, discrepancy_id, tc_id)
                _set_ticket(cypress_results, ticket_key, discrepancy_id, tc_id, skip_shared=True)

        await emit(job, "module3_done", {"bugs_created": len(bugs_created)})

        # ── 11. Final result ────────────────────────────────────────
        defect_tests = [test for test in tests if test.get("mode") == "defect_first"]
        coverage_tests = [test for test in tests if test.get("mode") == "coverage_first"]
        defect_results = [result for result in cypress_results if result.get("mode") == "defect_first"]
        coverage_results = [result for result in cypress_results if result.get("mode") == "coverage_first"]

        job.result = {
            "story_key":   story_key,
            "screen_type": screen_type,
            "app_url": app_url,
            "nav_path": nav_path,
            "uvri_pre":    uvri_pre,
            "uvri_post":   uvri_post,
            "delta":       uvri_post - uvri_pre,
            "subterms_pre":  sub_pre,
            "subterms_post": sub_post,
            "explicit_ACs":  explicit_ACs,
            "implicit_ACs":  implicit_ACs,
            "static_ACs":    static_ACs,
            "dynamic_ACs":   dynamic_ACs,
            "all_discrepancies":            verified,
            "high_confidence_discrepancies":   high_confidence,
            "medium_confidence_discrepancies": medium_confidence,
            "low_confidence_discrepancies":    low_confidence,
            "tests":           tests,
            "test_breakdown": {
                "defect_first": {
                    "generated": len(defect_tests),
                    "executed": len(defect_results),
                    "passed": sum(1 for item in defect_results if item.get("passed") is True),
                    "failed": sum(1 for item in defect_results if item.get("confirmed_fault") is True),
                    "skipped": sum(1 for item in defect_results if item.get("passed") is None),
                },
                "coverage_first": {
                    "generated": len(coverage_tests),
                    "executed": len(coverage_results),
                    "passed": sum(1 for item in coverage_results if item.get("passed") is True),
                    "failed": sum(1 for item in coverage_results if item.get("confirmed_fault") is True),
                    "skipped": sum(1 for item in coverage_results if item.get("passed") is None),
                },
            },
            "cypress_results": cypress_results,
            "bugs_created":    bugs_created,
            "exports": {
                "docx": docx_path,
                "markdown": markdown_path,
            },
        }
        _persist_result(story_key, job.result)
        job.status = "completed"
        await emit(job, "done", job.result)

    except httpx.HTTPStatusError as e:
        job.status = "failed"
        job.error = (
            f"Jira API error: {e.response.status_code} "
            f"{e.response.text[:200]}"
        )
        await emit(job, "error", {"message": job.error})
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        await emit(job, "error", {"message": job.error})