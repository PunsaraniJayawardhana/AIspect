# backend/pipeline/module2_validator.py

import os
import json
import asyncio
from typing import Dict, Any, List

from pipeline.module2.multipass_validator import run_multipass_validation
from pipeline.module2.confidence_index import compute_confidence_index


def run_module2(module1_output: Dict[str, Any]) -> Dict[str, Any]:
    """
    Entry point for Module 2.
    
    Args:
        module1_output: The enriched requirement set produced by Module 1.
    
    Returns:
        A dict containing:
        - ticket_id
        - all_discrepancies: full list with CI scores
        - high_confidence: list for Module 3 (CI >= HIGH threshold)
        - medium_confidence: list for human review
        - summary: counts per level
    """
    # Accept multiple possible keys for compatibility with Module 1 outputs
    ticket_id = module1_output.get("ticket_id") or module1_output.get("story_key") or "UNKNOWN"
    criteria = (
        module1_output.get("enriched_acceptance_criteria")
        or module1_output.get("enriched_ACs")
        or module1_output.get("enriched_acceptance_criteria_list")
        or []
    )
    # Images may be named `design_images` or `design_images_b64`
    design_images = (
        module1_output.get("design_images")
        or module1_output.get("design_images_b64")
        or module1_output.get("design_images_base64")
        or []
    )
    
    # Read config from environment
    n_passes = int(os.environ.get("MODULE2_PASSES", 5))
    model = os.environ.get("MODULE2_MODEL", "claude-sonnet-4-6")
    high_threshold = float(os.environ.get("CI_HIGH_THRESHOLD", 0.80))
    medium_threshold = float(os.environ.get("CI_MEDIUM_THRESHOLD", 0.60))
    
    print(f"\n[Module2] Starting validation for ticket: {ticket_id}")
    print(f"[Module2] Criteria count: {len(criteria)}, Images: {len(design_images)}, Passes: {n_passes}")
    
    if not criteria:
        raise ValueError(f"[Module2] No acceptance criteria received for ticket {ticket_id}")
    if not design_images:
        raise ValueError(f"[Module2] No design images received for ticket {ticket_id}")
    
    # Step 1: Run N validation passes (multipass validator is async)
    all_pass_results = asyncio.run(run_multipass_validation(criteria, design_images, n_passes))
    
    # Step 2: Compute confidence index and classify
    all_discrepancies = compute_confidence_index(
        all_pass_results, n_passes, high_threshold, medium_threshold
    )
    
    high_confidence = [
        d for d in all_discrepancies
        if d["confidence_label"] == "HIGH"
    ]
    medium_confidence = [
        d for d in all_discrepancies
        if d["confidence_label"] == "MEDIUM"
    ]
    low_confidence = [
        d for d in all_discrepancies
        if d["confidence_label"] == "LOW"
    ]

    output = {
        "ticket_id": ticket_id,
        # Full list for the output file
        "discrepancies": all_discrepancies,
        # Filtered lists for Module 3 and human review
        "high_confidence": high_confidence,
        "medium_confidence": medium_confidence,
        "summary": {
            "total_candidates": len(all_discrepancies),
            "high": len(high_confidence),
            "medium": len(medium_confidence),
            "low": len(low_confidence),
            "n_passes": n_passes,
        }
    }

    return output