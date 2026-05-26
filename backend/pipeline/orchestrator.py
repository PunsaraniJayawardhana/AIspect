import httpx
from backend.jobs.job_store import Job
from backend.integrations.jira_client import (
    fetch_single_story,
    fetch_media_as_base64,
    create_bug_ticket,
)
from backend.pipeline.module1.adf_parser import parse_adf
from backend.pipeline.module1.screen_classifier import classify_screen_type
from backend.pipeline.module1.uvri import compute_uvri
from backend.pipeline.module1.inference import infer_implicit_elements
from backend.pipeline.module2.multipass_validator import run_multipass_validation
from backend.pipeline.module2.confidence_index import compute_confidence_index
from backend.pipeline.module3.cypress_runner import get_confirmed_faults, run_cypress_tests
from backend.pipeline.module3.docx_exporter import export_to_docx, export_to_markdown
from backend.pipeline.module3.test_generator import run_test_generator


async def emit(job: Job, step: str, payload: dict = None):
    """Push a progress event to the job's stream."""
    job.current_step = step
    await job.event_queue.put({"step": step, "payload": payload or {}})


async def process_one_story(job: Job, story_key: str, app_url: str = None):
    try:
        job.status = "running"

        # ── 1. Fetch the ticket ─────────────────────────────────────
        await emit(job, "fetching_ticket")
        story = await fetch_single_story(story_key)

        if story["description_adf"] is None:
            job.status = "completed"
            job.result = {"skipped": True, "reason": "null description"}
            await emit(job, "done", job.result)
            return

        # ── 2. Parse the ADF tree ───────────────────────────────────
        await emit(job, "parsing_adf")
        parsed = parse_adf(story["description_adf"])
        # parsed = {
        #   "story_text": str,
        #   "nav_path": str,
        #   "explicit_ACs": List[str],
        #   "media_uuids": List[str],
        # }

        # ── 3. Download embedded design images ──────────────────────
        await emit(job, "downloading_design_images",
                   {"count": len(parsed["media_uuids"])})
        design_images_b64 = []
        for uuid_ in parsed["media_uuids"]:
            img = await fetch_media_as_base64(uuid_)
            design_images_b64.append(img)

        # ── 4. Module 1 — Screen classification ─────────────────────
        await emit(job, "classifying_screen_type")
        screen_type = await classify_screen_type(parsed)
        await emit(job, "screen_type_classified", {"screen_type": screen_type})

        # ── 5. Module 1 — UVRI pre-enrichment ───────────────────────
        await emit(job, "computing_uvri_pre")
        uvri_pre, sub_pre = await compute_uvri(parsed["explicit_ACs"], screen_type)
        await emit(job, "uvri_pre_done",
                   {"uvri": uvri_pre, "subterms": sub_pre})

        # ── 6. Module 1 — Implicit inference ────────────────────────
        await emit(job, "running_implicit_inference")
        implicit_ACs = await infer_implicit_elements(parsed, screen_type)
        await emit(job, "inference_done",
                   {"implicit_ACs": implicit_ACs})

        enriched_ACs = parsed["explicit_ACs"] + implicit_ACs

        # ── 7. Module 1 — UVRI post-enrichment ──────────────────────
        await emit(job, "computing_uvri_post")
        uvri_post, sub_post = await compute_uvri(enriched_ACs, screen_type)
        await emit(job, "uvri_post_done", {
            "uvri": uvri_post,
            "subterms": sub_post,
            "delta": uvri_post - uvri_pre,
        })

        # ── 8. Module 2 — Multi-pass validation ─────────────────────
        await emit(job, "module2_started",
                   {"total_passes": 5})
        passes = await run_multipass_validation(
            enriched_ACs, design_images_b64, n=5
        )
        await emit(job, "module2_passes_complete")

        verified = compute_confidence_index(passes)
        await emit(job, "module2_done",
                   {"verified_discrepancies": verified})

        # ── 9. Module 3 — Test generation ───────────────────────────
        await emit(job, "module3_started")
        tests = run_test_generator(
            verified_discrepancies=verified,
            explicit_acs=parsed["explicit_ACs"],
            implicit_acs=implicit_ACs,
            story_text=parsed["story_text"],
            story_key=story_key,
            app_url=app_url,
            nav_path=parsed.get("nav_path", ""),
        )
        export_to_docx(tests, story_key, f"backend/scripts/fixtures/{story_key}_test_cases.docx")
        export_to_markdown(tests, story_key, f"backend/scripts/fixtures/{story_key}_test_cases.md")
        await emit(job, "tests_generated", {"test_count": len(tests)})

        # ── 10. Module 3 — Cypress execution ────────────────────────
        cypress_results = []
        bugs_created = []
        if app_url:
            await emit(job, "running_cypress")
            cypress_results = run_cypress_tests(tests)
            await emit(job, "cypress_done", {"results": cypress_results})

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

        await emit(job, "module3_done", {"bugs_created": len(bugs_created)})

        # ── 11. Final result ────────────────────────────────────────
        job.result = {
            "story_key": story_key,
            "screen_type": screen_type,
            "uvri_pre": uvri_pre,
            "uvri_post": uvri_post,
            "delta": uvri_post - uvri_pre,
            "subterms_pre": sub_pre,
            "subterms_post": sub_post,
            "explicit_ACs": parsed["explicit_ACs"],
            "implicit_ACs": implicit_ACs,
            "verified_discrepancies": verified,
            "tests": tests,
            "cypress_results": cypress_results,
            "bugs_created": bugs_created,
        }
        job.status = "completed"
        await emit(job, "done", job.result)

    except httpx.HTTPStatusError as e:
        job.status = "failed"
        job.error = f"Jira API error: {e.response.status_code} {e.response.text[:200]}"
        await emit(job, "error", {"message": job.error})
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        await emit(job, "error", {"message": job.error})