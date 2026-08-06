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

TICKET_ID = "EXC-1"  # change this to any ticket
N_IMPLICIT = 1       # passes for implicit ACs
N_ENRICHED = 5       # passes for the enriched (explicit + implicit) AC set

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



def load_module1_fixture(ticket_id: str) -> dict:
    """Load Module 1 fixture to get ACs and design image."""
    fixture_path = pathlib.Path(
        f"output/module1_fixtures/{ticket_id}.json"
    )
    if not fixture_path.exists():
        raise FileNotFoundError(
            f"No fixture found for {ticket_id}. "
            f"Run the pipeline once first to generate it."
        )
    with open(fixture_path, "r", encoding="utf-8") as f:
        return json.load(f)


async def run_dual_mode(ticket_id: str):
    """
    Run dual-mode validation:
    - Implicit ACs alone: N=1 pass
    - Enriched ACs (explicit + implicit combined): N=5 passes
    """
    print(f"\n{'='*60}")
    print(f"DUAL MODE VALIDATION — {ticket_id}")
    print(f"{'='*60}")

    # Load fixture — no Jira API call needed
    fixture = load_module1_fixture(ticket_id)

    explicit_ACs      = fixture["explicit_ACs"]
    implicit_ACs      = fixture["implicit_ACs"]
    static_ACs        = fixture["static_ACs"]
    design_images_b64 = fixture["design_images_b64"]

    # Separate static explicit and static implicit
    explicit_static = [
        ac for ac in static_ACs
        if ac in explicit_ACs
    ]
    implicit_static = [
        ac for ac in static_ACs
        if ac in implicit_ACs

    # Enriched = explicit + implicit static ACs merged into one set (deduped,
    # order preserved) so they get validated together as a single pass-set.
    enriched_static = list(explicit_static)
    for ac in implicit_static:
        if ac not in enriched_static:
            enriched_static.append(ac)

    print(f"Implicit static ACs: {len(implicit_static)} → N={N_IMPLICIT}")
    print(f"Enriched static ACs (explicit+implicit): {len(enriched_static)} → N={N_ENRICHED}")


    implicit_passes = []
    if implicit_static:
        print(f"\n[Implicit] Running {N_IMPLICIT} pass...")

        implicit_passes = await run_multipass_validation(
            implicit_static,
            design_images_b64,
            n=N_IMPLICIT
        )

    # ── Run N=5 on enriched (explicit + implicit combined) ACs ───────
    enriched_passes = []
    if enriched_static:
        print(f"\n[Enriched] Running {N_ENRICHED} passes...")
        enriched_passes = await run_multipass_validation(
            enriched_static,
            design_images_b64,
            n=N_ENRICHED
        )

    # ── Compute CI separately ────────────────────────────────────────
    verified_implicit = compute_confidence_index(
        implicit_passes, n_passes=N_IMPLICIT
    ) if implicit_passes else []

    verified_enriched = compute_confidence_index(
        enriched_passes, n_passes=N_ENRICHED
    ) if enriched_passes else []

    # ── Print results ────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"RESULTS — {ticket_id}")
    print(f"{'─'*60}")
    print(f"Implicit findings: {len(verified_implicit)}")
    for d in verified_implicit:
        print(f"  [{d['confidence_label']}] CI={d['confidence_index']} "
              f"— {d['element_name']}")

    print(f"\nEnriched (explicit+implicit) findings: {len(verified_enriched)}")
    for d in verified_enriched:
        print(f"  [{d['confidence_label']}] CI={d['confidence_index']} "
              f"— {d['element_name']}")

# ── Save output ──────────────────────────────────────────────────
    output = {
        "ticket_id":   ticket_id,
        "screen_type": fixture["screen_type"],
        "implicit_validation": {
            "n_passes":      N_IMPLICIT,
            "ac_count":      len(implicit_static),
            "discrepancies": verified_implicit,
            "summary": {
                "high":   len([d for d in verified_implicit
                               if d["confidence_label"] == "HIGH"]),
                "medium": len([d for d in verified_implicit
                               if d["confidence_label"] == "MEDIUM"]),
                "low":    len([d for d in verified_implicit
                               if d["confidence_label"] == "LOW"]),
            }
        },
        "enriched_validation": {
            "n_passes":      N_ENRICHED,
            "ac_count":      len(enriched_static),
            "discrepancies": verified_enriched,
            "summary": {
                "high":   len([d for d in verified_enriched
                               if d["confidence_label"] == "HIGH"]),
                "medium": len([d for d in verified_enriched
                               if d["confidence_label"] == "MEDIUM"]),
                "low":    len([d for d in verified_enriched
                               if d["confidence_label"] == "LOW"]),
            }
        },
    }

    out_path = OUTPUT_DIR / f"{ticket_id}_dual_mode.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[Done] Output saved to {out_path}")
    return output


if __name__ == "__main__":
    import asyncio

    # Change ticket ID here or pass as argument
    ticket = sys.argv[1] if len(sys.argv) > 1 else TICKET_ID
    asyncio.run(run_dual_mode(ticket))