"""
Export a live Module 2 snapshot for a Jira story.

This script runs Module 1 parsing + Module 2 validation directly and writes
its output to output/module2_output/<story_key>.json so Module 3 can consume it.

Usage:
    python -m backend.scripts.export_module2_snapshot EXC-7
"""

import argparse
import asyncio
import json
import pathlib
import sys

from backend.integrations.jira_client import fetch_attachment_as_base64, fetch_single_story
from backend.pipeline.module1.adf_parser import parse_adf
from backend.pipeline.module1.inference import infer_implicit_elements
from backend.pipeline.module1.screen_classifier import classify_screen_type
from backend.pipeline.module2.confidence_index import compute_confidence_index
from backend.pipeline.module2.multipass_validator import run_multipass_validation
from backend.pipeline.orchestrator import classify_acs

OUTPUT_DIR = pathlib.Path("output/module2_output")


async def export_module2_snapshot(story_key: str, n_passes: int = 5) -> pathlib.Path:
    story = await fetch_single_story(story_key)
    if story.get("description_adf") is None:
        raise ValueError(f"Story {story_key} has no description ADF payload")

    parsed = parse_adf(story["description_adf"])
    screen_type = await classify_screen_type(parsed)
    implicit_acs = await infer_implicit_elements(parsed, screen_type)

    explicit_acs = parsed.get("explicit_ACs", [])
    enriched_acs = explicit_acs + implicit_acs
    canonical_acs = [
        {
            "ac_id": f"AC-{idx:02d}",
            "text": ac,
            "type": "explicit" if idx <= len(explicit_acs) else "implicit",
        }
        for idx, ac in enumerate(enriched_acs, start=1)
    ]
    static_acs, dynamic_acs = classify_acs(enriched_acs)

    image_attachments = [
        attachment for attachment in story.get("attachments", [])
        if attachment.get("mime_type", "").startswith("image/")
    ]
    design_images_b64 = []
    for attachment in image_attachments:
        design_images_b64.append(await fetch_attachment_as_base64(attachment["content_url"]))

    passes = await run_multipass_validation(static_acs, design_images_b64, n=n_passes)
    verified = compute_confidence_index(passes, n_passes=n_passes, canonical_acs=canonical_acs)

    high_confidence = [item for item in verified if item.get("confidence_label") == "HIGH"]
    medium_confidence = [item for item in verified if item.get("confidence_label") == "MEDIUM"]
    low_confidence = [item for item in verified if item.get("confidence_label") == "LOW"]

    payload = {
        "ticket_id": story_key,
        "screen_type": screen_type,
        "high_confidence": high_confidence,
        "medium_confidence": medium_confidence,
        "all_discrepancies": verified,
        "dynamic_ACs": dynamic_acs,
        "summary": {
            "total_candidates": len(verified),
            "high": len(high_confidence),
            "medium": len(medium_confidence),
            "low": len(low_confidence),
            "n_passes": n_passes,
            "static_acs_validated": len(static_acs),
            "dynamic_acs_deferred": len(dynamic_acs),
        },
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{story_key}.json"
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Export a live Module 2 output snapshot for one Jira story")
    parser.add_argument("story_key", help="Jira story key, e.g. EXC-1")
    parser.add_argument("--passes", type=int, default=5, help="Number of Module 2 validation passes")
    args = parser.parse_args()

    output_path = await export_module2_snapshot(args.story_key, n_passes=args.passes)
    print(f"Wrote Module 2 snapshot: {output_path}")
    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
