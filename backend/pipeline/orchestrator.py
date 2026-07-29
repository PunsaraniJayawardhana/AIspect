import json
import os
import pathlib
import httpx
from jobs.job_store import Job
from integrations.jira_client import (
    fetch_single_story,
    fetch_attachment_as_base64,
    create_bug_ticket,
)

from pipeline.module1.adf_parser import parse_adf
from pipeline.module1.screen_classifier import classify_screen_type
from pipeline.module1.uvri import compute_uvri
from pipeline.module1.inference import infer_implicit_elements
from pipeline.module2.multipass_validator import run_multipass_validation
from pipeline.module2.confidence_index import compute_confidence_index
from pipeline.module3.test_generator import generate_dual_mode_tests
from pipeline.module3.cypress_runner import execute_cypress


RESULTS_DIR        = pathlib.Path("output/results")
MODULE2_OUTPUT_DIR = pathlib.Path("output/module2_output")
MODULE1_FIXTURES_DIR = pathlib.Path("output/module1_fixtures")

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


def _persist_module1_fixture(story_key: str, data: dict) -> None:
    """
    Save Module 1 output as a fixture file.
    On subsequent runs Module 2 loads this instead of re-running Module 1.
    Saves Jira API calls and Claude inference API credits.
    """
    MODULE1_FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    (MODULE1_FIXTURES_DIR / f"{story_key}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[Module1] Fixture saved to "
          f"output/module1_fixtures/{story_key}.json")


def _load_module1_fixture(story_key: str) -> dict:
    """
    Load Module 1 fixture if it exists.
    Returns the fixture dict or None if not found.
    """
    fixture_path = MODULE1_FIXTURES_DIR / f"{story_key}.json"
    if fixture_path.exists():
        print(f"[Module1] Fixture found — loading from "
              f"output/module1_fixtures/{story_key}.json")
        with open(fixture_path, "r", encoding="utf-8") as f:
            return json.load(f)
    print(f"[Module1] No fixture found for {story_key} "
          f"— running full Module 1")
    return None


async def process_one_story(job: Job, story_key: str, app_url: str = None):
    try:
        job.status = "running"

        # ── Read N from environment variable ────────────────────────
        n_passes = int(os.environ.get("MODULE2_PASSES", 5))
        print(f"[Module2] N passes set to: {n_passes}")

        # ── Check for existing Module 1 fixture ─────────────────────
        fixture = _load_module1_fixture(story_key)

        if fixture:
            # ── Load from fixture — skip Module 1 entirely ──────────
            print(f"[Module1] Skipping Jira fetch, ADF parse, "
                  f"image download, implicit inference")
            screen_type       = fixture["screen_type"]
            uvri_pre          = fixture["uvri_pre"]
            uvri_post         = fixture["uvri_post"]
            sub_pre           = fixture["subterms_pre"]
            sub_post          = fixture["subterms_post"]
            explicit_ACs      = fixture["explicit_ACs"]
            implicit_ACs      = fixture["implicit_ACs"]
            enriched_ACs      = fixture["enriched_ACs"]
            static_ACs        = fixture["static_ACs"]
            dynamic_ACs       = fixture["dynamic_ACs"]
            design_images_b64 = fixture["design_images_b64"]

            print(f"[Module1] Loaded from fixture: "
                  f"screen_type={screen_type}, "
                  f"static_ACs={len(static_ACs)}, "
                  f"dynamic_ACs={len(dynamic_ACs)}, "
                  f"images={len(design_images_b64)}")

            await emit(job, "module1_loaded_from_fixture", {
                "screen_type":   screen_type,
                "static_count":  len(static_ACs),
                "dynamic_count": len(dynamic_ACs),
            })

        else:
            # ── Run full Module 1 ────────────────────────────────────

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

            # ── 3. Download design images ────────────────────────────
            image_attachments = [
                a for a in story["attachments"]
                if a.get("mime_type", "").startswith("image/")
            ]
            await emit(job, "downloading_design_images",
                       {"count": len(image_attachments)})
            design_images_b64 = []
            for attachment in image_attachments:
                img = await fetch_attachment_as_base64(
                    attachment["content_url"]
                )
                design_images_b64.append(img)

            # ── 4. Module 1 — Screen classification ──────────────────
            await emit(job, "classifying_screen_type")
            screen_type = await classify_screen_type(parsed)
            await emit(job, "screen_type_classified",
                       {"screen_type": screen_type})

            # ── 5. Module 1 — UVRI pre-enrichment ────────────────────
            await emit(job, "computing_uvri_pre")
            uvri_pre, sub_pre = await compute_uvri(
                parsed["explicit_ACs"], screen_type
            )
            await emit(job, "uvri_pre_done",
                       {"uvri": uvri_pre, "subterms": sub_pre})

            # ── 6. Module 1 — Implicit inference ─────────────────────
            await emit(job, "running_implicit_inference")
            implicit_ACs = await infer_implicit_elements(
                parsed, screen_type
            )
            await emit(job, "inference_done",
                       {"implicit_ACs": implicit_ACs})

            explicit_ACs = parsed["explicit_ACs"]
            enriched_ACs = explicit_ACs + implicit_ACs

            # ── 7. Module 1 — UVRI post-enrichment ───────────────────
            await emit(job, "computing_uvri_post")
            uvri_post, sub_post = await compute_uvri(
                enriched_ACs, screen_type
            )
            await emit(job, "uvri_post_done", {
                "uvri":     uvri_post,
                "subterms": sub_post,
                "delta":    uvri_post - uvri_pre,
            })

            # ── 7.5 — AC Pre-Classification ───────────────────────────
            await emit(job, "classifying_acs")
            static_ACs, dynamic_ACs = classify_acs(enriched_ACs)
            await emit(job, "acs_classified", {
                "static_count":  len(static_ACs),
                "dynamic_count": len(dynamic_ACs),
            })

            # ── Save Module 1 fixture for future runs ─────────────────
            # Next time this ticket is processed, Module 1 is skipped
            # and this fixture is loaded directly — saving API credits
            _persist_module1_fixture(story_key, {
                "ticket_id":          story_key,
                "screen_type":        screen_type,
                "uvri_pre":           uvri_pre,
                "uvri_post":          uvri_post,
                "subterms_pre":       sub_pre,
                "subterms_post":      sub_post,
                "explicit_ACs":       explicit_ACs,
                "implicit_ACs":       implicit_ACs,
                "enriched_ACs":       enriched_ACs,
                "static_ACs":         static_ACs,
                "dynamic_ACs":        dynamic_ACs,
                "design_images_b64":  design_images_b64,
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

        verified = compute_confidence_index(passes, n_passes=n_passes)

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
        tests = await generate_dual_mode_tests(
            enriched_ACs,
            high_confidence
        )
        await emit(job, "tests_generated", {"test_count": len(tests)})

        # ── 10. Module 3 — Cypress execution ────────────────────────
        cypress_results = []
        if app_url:
            await emit(job, "running_cypress")
            cypress_results = await execute_cypress(tests, app_url)
            await emit(job, "cypress_done", {"results": cypress_results})

        # ── 11. Module 3 — Bug ticket creation ──────────────────────
        bugs_created = []
        for result in cypress_results:
            if result.get("mode") == "defect" and \
               result.get("passed") is False:
                await emit(job, "creating_bug_ticket",
                           {"discrepancy": result["discrepancy"]["element"]})
                bug = await create_bug_ticket(
                    summary=(
                        f"[AIspect] {result['discrepancy']['element']}"
                    ),
                    description=result["discrepancy"]["description"],
                    parent_story_key=story_key,
                    severity=result["discrepancy"]["severity"],
                )
                bugs_created.append(bug["key"])

        # ── 12. Final result ─────────────────────────────────────────
        job.result = {
            "story_key":   story_key,
            "screen_type": screen_type,
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
            "cypress_results": cypress_results,
            "bugs_created":    bugs_created,
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
