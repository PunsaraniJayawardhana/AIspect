"""
Dual-Mode Validation Script
Runs explicit ACs at N=5 and implicit ACs at N=1
Produces separate output files for teammate analysis
Does NOT affect the main pipeline or Module 2 output
"""

import json
import os
import sys
import pathlib
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add backend to path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from pipeline.module2.multipass_validator import run_multipass_validation
from pipeline.module2.confidence_index import compute_confidence_index

# ─── Configuration ───────────────────────────────────────────────────

TICKET_ID = "EXC-1"  # change this to any ticket
N_EXPLICIT = 5       # passes for explicit ACs
N_IMPLICIT = 1       # passes for implicit ACs

OUTPUT_DIR = pathlib.Path("output/dual_mode_results")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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
    - Explicit ACs: N=5 passes
    - Implicit ACs: N=1 pass
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
    ]

    print(f"\nExplicit static ACs: {len(explicit_static)} → N={N_EXPLICIT}")
    print(f"Implicit static ACs: {len(implicit_static)} → N={N_IMPLICIT}")

    # ── Run N=5 on explicit ACs ──────────────────────────────────────
    explicit_passes = []
    if explicit_static:
        print(f"\n[Explicit] Running {N_EXPLICIT} passes...")
        explicit_passes = await run_multipass_validation(
            explicit_static,
            design_images_b64,
            n=N_EXPLICIT
        )

    # ── Run N=1 on implicit ACs ──────────────────────────────────────
    implicit_passes = []
    if implicit_static:
        print(f"\n[Implicit] Running {N_IMPLICIT} pass...")
        implicit_passes = await run_multipass_validation(
            implicit_static,
            design_images_b64,
            n=N_IMPLICIT
        )

    # ── Compute CI separately ────────────────────────────────────────
    verified_explicit = compute_confidence_index(
        explicit_passes, n_passes=N_EXPLICIT
    ) if explicit_passes else []

    verified_implicit = compute_confidence_index(
        implicit_passes, n_passes=N_IMPLICIT
    ) if implicit_passes else []

    # ── Print results ────────────────────────────────────────────────
    print(f"\n{'─'*60}")
    print(f"RESULTS — {ticket_id}")
    print(f"{'─'*60}")
    print(f"Explicit findings: {len(verified_explicit)}")
    for d in verified_explicit:
        print(f"  [{d['confidence_label']}] CI={d['confidence_index']} "
              f"— {d['element_name']}")

    print(f"\nImplicit findings: {len(verified_implicit)}")
    for d in verified_implicit:
        print(f"  [{d['confidence_label']}] CI={d['confidence_index']} "
              f"— {d['element_name']}")

    # ── Save output ──────────────────────────────────────────────────
    output = {
        "ticket_id":   ticket_id,
        "screen_type": fixture["screen_type"],
        "explicit_validation": {
            "n_passes":      N_EXPLICIT,
            "ac_count":      len(explicit_static),
            "discrepancies": verified_explicit,
            "summary": {
                "high":   len([d for d in verified_explicit
                               if d["confidence_label"] == "HIGH"]),
                "medium": len([d for d in verified_explicit
                               if d["confidence_label"] == "MEDIUM"]),
                "low":    len([d for d in verified_explicit
                               if d["confidence_label"] == "LOW"]),
            }
        },
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