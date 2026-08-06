"""
Dual-mode Module 2 validation runner.

Runs explicit static ACs with N=5 and implicit static ACs with N=1 using
live Jira story data (no fixtures).

Usage:
    python -m backend.scripts.test_dual_mode_validation EXC-1
"""

import asyncio
import json
import pathlib
import sys

from dotenv import load_dotenv

from backend.integrations.jira_client import fetch_attachment_as_base64, fetch_single_story
from backend.pipeline.module1.adf_parser import parse_adf
from backend.pipeline.module1.inference import infer_implicit_elements
from backend.pipeline.module1.screen_classifier import classify_screen_type
from backend.pipeline.module2.confidence_index import compute_confidence_index
from backend.pipeline.module2.multipass_validator import run_multipass_validation
from backend.pipeline.orchestrator import classify_acs

load_dotenv()

N_EXPLICIT = 5
N_IMPLICIT = 1
OUTPUT_DIR = pathlib.Path("output/dual_mode_results")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def _load_story_inputs(story_key: str) -> dict:
    story = await fetch_single_story(story_key)
    if story.get("description_adf") is None:
        raise ValueError(f"Story {story_key} has no description ADF payload")

    parsed = parse_adf(story["description_adf"])
    screen_type = await classify_screen_type(parsed)
    implicit_acs = await infer_implicit_elements(parsed, screen_type)
    explicit_acs = parsed.get("explicit_ACs", [])
    enriched_acs = explicit_acs + implicit_acs
    static_acs, _ = classify_acs(enriched_acs)

    image_attachments = [
        attachment for attachment in story.get("attachments", [])
        if attachment.get("mime_type", "").startswith("image/")
    ]
    design_images_b64 = []
    for attachment in image_attachments:
        design_images_b64.append(await fetch_attachment_as_base64(attachment["content_url"]))

    return {
        "screen_type": screen_type,
        "explicit_ACs": explicit_acs,
        "implicit_ACs": implicit_acs,
        "static_ACs": static_acs,
        "design_images_b64": design_images_b64,
    }


async def run_dual_mode(story_key: str) -> dict:
    print(f"\n{'=' * 60}")
    print(f"DUAL MODE VALIDATION - {story_key}")
    print(f"{'=' * 60}")

    inputs = await _load_story_inputs(story_key)
    explicit_acs = inputs["explicit_ACs"]
    implicit_acs = inputs["implicit_ACs"]
    canonical_acs = [
        {
            "ac_id": f"AC-{idx:02d}",
            "text": ac,
            "type": "explicit" if idx <= len(explicit_acs) else "implicit",
        }
        for idx, ac in enumerate(explicit_acs + implicit_acs, start=1)
    ]
    static_acs = inputs["static_ACs"]
    design_images_b64 = inputs["design_images_b64"]

    explicit_static = [ac for ac in static_acs if ac in explicit_acs]
    implicit_static = [ac for ac in static_acs if ac in implicit_acs]

    print(f"\nExplicit static ACs: {len(explicit_static)} -> N={N_EXPLICIT}")
    print(f"Implicit static ACs: {len(implicit_static)} -> N={N_IMPLICIT}")

    explicit_passes = []
    if explicit_static:
        print(f"\n[Explicit] Running {N_EXPLICIT} passes...")
        explicit_passes = await run_multipass_validation(explicit_static, design_images_b64, n=N_EXPLICIT)

    implicit_passes = []
    if implicit_static:
        print(f"\n[Implicit] Running {N_IMPLICIT} pass...")
        implicit_passes = await run_multipass_validation(implicit_static, design_images_b64, n=N_IMPLICIT)

    verified_explicit = (
        compute_confidence_index(explicit_passes, n_passes=N_EXPLICIT, canonical_acs=canonical_acs)
        if explicit_passes
        else []
    )
    verified_implicit = (
        compute_confidence_index(implicit_passes, n_passes=N_IMPLICIT, canonical_acs=canonical_acs)
        if implicit_passes
        else []
    )

    print(f"\n{'-' * 60}")
    print(f"RESULTS - {story_key}")
    print(f"{'-' * 60}")
    print(f"Explicit findings: {len(verified_explicit)}")
    print(f"Implicit findings: {len(verified_implicit)}")

    output = {
        "ticket_id": story_key,
        "screen_type": inputs["screen_type"],
        "explicit_validation": {
            "n_passes": N_EXPLICIT,
            "ac_count": len(explicit_static),
            "discrepancies": verified_explicit,
        },
        "implicit_validation": {
            "n_passes": N_IMPLICIT,
            "ac_count": len(implicit_static),
            "discrepancies": verified_implicit,
        },
    }

    out_path = OUTPUT_DIR / f"{story_key}_dual_mode.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDone. Output saved to {out_path}")
    return output


if __name__ == "__main__":
    ticket = sys.argv[1] if len(sys.argv) > 1 else "EXC-1"
    asyncio.run(run_dual_mode(ticket))
