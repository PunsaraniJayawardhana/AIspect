import re
from typing import List, Dict, Any
from difflib import SequenceMatcher

SEVERITY_MAP = {
    "Missing Element": "HIGH",
    "Business Rule Violation": "HIGH",
    "Wrong Label": "MEDIUM",
    "Layout Constraint Mismatch": "MEDIUM",
    "Interaction Flow Error": "LOW",
}

VALID_DISCREPANCY_TYPES = set(SEVERITY_MAP.keys())


def _normalize_text(text: str) -> str:
    return re.sub(r'[^a-z0-9\s]', '', text.lower()).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(
        None, _normalize_text(a), _normalize_text(b)
    ).ratio()


def _find_canonical_group(
    candidate: Dict,
    canonical_groups: List[Dict],
    similarity_threshold: float = 0.55,
) -> int:
    for idx, group in enumerate(canonical_groups):
        same_type = (
            candidate.get("discrepancy_type", "").strip() ==
            group["discrepancy_type"]
        )
        if not same_type:
            continue

        name_sim = _similarity(
            candidate.get("element_name", ""),
            group["element_name"]
        )
        desc_sim = _similarity(
            candidate.get("description", ""),
            group["description"]
        )

        if name_sim >= similarity_threshold or desc_sim >= similarity_threshold:
            return idx

    return -1


def _generate_feedback(discrepancy: Dict) -> str:
    dtype = discrepancy["discrepancy_type"]
    element = discrepancy["element_name"]
    location = discrepancy["location"]
    criterion = discrepancy["requirement_id"]
    confidence = discrepancy["confidence_label"]
    runs = discrepancy["identified_in_runs"]
    n = discrepancy["n_passes"]

    templates = {
        "Missing Element": (
            f"The '{element}' is missing from the design at {location}. "
            f"This element is required by {criterion} and was not found in "
            f"{runs} out of {n} validation passes. "
            f"QA engineers would expect this element to be present on this screen."
        ),
        "Wrong Label": (
            f"The label or text on '{element}' at {location} does not match "
            f"what is specified in {criterion}. "
            f"This mismatch was detected in {runs} out of {n} validation passes "
            f"and is classified as {confidence} confidence."
        ),
        "Business Rule Violation": (
            f"The design of '{element}' at {location} violates a business rule "
            f"defined in {criterion}. "
            f"This was flagged in {runs} out of {n} validation passes, "
            f"indicating a significant requirement deviation."
        ),
        "Layout Constraint Mismatch": (
            f"The positioning or layout of '{element}' at {location} does not "
            f"satisfy the layout constraints in {criterion}. "
            f"Detected in {runs} out of {n} passes."
        ),
        "Interaction Flow Error": (
            f"The interaction behavior of '{element}' at {location} deviates "
            f"from the flow described in {criterion}. "
            f"This was identified in {runs} out of {n} validation passes."
        ),
    }

    return templates.get(
        dtype,
        f"A discrepancy was detected on '{element}' at {location} "
        f"related to {criterion}. Confidence: {confidence} "
        f"({runs}/{n} passes)."
    )


def compute_confidence_index(
    all_pass_results: List[List[Dict[str, Any]]],
    n_passes: int = 5,
    high_threshold: float = 0.80,
    medium_threshold: float = 0.60,
) -> List[Dict[str, Any]]:

    canonical_groups: List[Dict] = []

    for pass_idx, pass_results in enumerate(all_pass_results):
        seen_in_this_pass = set()

        for candidate in pass_results:
            dtype = candidate.get("discrepancy_type", "")
            ename = candidate.get("element_name", "")

            if not ename or not dtype:
                continue
            if dtype not in VALID_DISCREPANCY_TYPES:
                continue

            group_idx = _find_canonical_group(candidate, canonical_groups)

            if group_idx == -1:
                new_idx = len(canonical_groups)
                canonical_groups.append({
                    "element_name": ename,
                    "discrepancy_type": dtype,
                    "violated_criterion": candidate.get("violated_criterion", ""),
                    "screen_region": candidate.get("screen_region", "unknown"),
                    "description": candidate.get("description", ""),
                    "run_count": 1,
                    "contributing_passes": [pass_idx],
                })
                # Mark this new group as seen in this pass immediately
                seen_in_this_pass.add((new_idx, pass_idx))
            else:
                key = (group_idx, pass_idx)
                if key not in seen_in_this_pass:
                    canonical_groups[group_idx]["run_count"] += 1
                    canonical_groups[group_idx][
                        "contributing_passes"
                    ].append(pass_idx)
                    seen_in_this_pass.add(key)

    print(f"\n[CI DEBUG] Final canonical_groups count: {len(canonical_groups)}")
    for g in canonical_groups:
        ci = g['run_count'] / n_passes
        print(f"  - '{g['element_name']}': "
              f"run_count={g['run_count']}, ci={ci:.2f}")

    results = []
    for ac_idx, group in enumerate(canonical_groups):
        ci = group["run_count"] / n_passes

        if ci >= high_threshold:
            confidence_label = "HIGH"
        elif ci >= medium_threshold:
            confidence_label = "MEDIUM"
        else:
            confidence_label = "LOW"

        severity = SEVERITY_MAP.get(group["discrepancy_type"], "MEDIUM")

        discrepancy = {
            "requirement_id": f"AC-{ac_idx + 1:02d}",
            "element_name": group["element_name"],
            "discrepancy_type": group["discrepancy_type"],
            "description": group["description"],
            "location": group["screen_region"],
            "confidence_index": round(ci, 2),
            "confidence_label": confidence_label,
            "identified_in_runs": group["run_count"],
            "n_passes": n_passes,
            "severity": severity,
            "violated_criterion": group["violated_criterion"],
        }

        discrepancy["feedback"] = _generate_feedback(discrepancy)
        results.append(discrepancy)

    results.sort(key=lambda x: x["confidence_index"], reverse=True)
    return results