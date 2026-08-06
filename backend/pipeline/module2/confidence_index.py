import re
import os
import anthropic
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
CANONICAL_AC_MATCH_THRESHOLD = 0.45

# Phrases that indicate Claude contradicted its own finding
SELF_CONTRADICTION_PHRASES = [
    "should be disregarded",
    "no discrepancy exists",
    "this is informational",
    "not a real finding",
    "disregard this",
    "this entry should be",
    "no issue exists",
    "this is not a defect",
    "informational only",
    "this note is informational",
    "no actual discrepancy",
    "not a discrepancy",
    "this finding should",
    "should not be flagged",
]


def _normalize_text(text: str) -> str:
    return re.sub(r'[^a-z0-9\s]', '', text.lower()).strip()


def _lexical_similarity(a: str, b: str) -> float:
    """Fast character-level similarity for pre-filtering only."""
    return SequenceMatcher(
        None, _normalize_text(a), _normalize_text(b)
    ).ratio()


def _quick_prefilter(candidate: Dict, group: Dict,
                     min_similarity: float = 0.30) -> bool:
    """
    Fast lexical pre-check before calling Claude.
    Returns False if findings are clearly different elements.
    Eliminates obvious non-matches without using the Claude API.
    """
    # Must be same discrepancy type
    if candidate.get("discrepancy_type", "").strip() != \
       group["discrepancy_type"]:
        return False

    # Check name similarity — if below 30% they are clearly different
    name_sim = _lexical_similarity(
        candidate.get("element_name", ""),
        group["element_name"]
    )
    return name_sim >= 0.30


def _are_same_discrepancy(
    client: anthropic.Anthropic,
    candidate: Dict,
    group: Dict,
    model: str,
) -> bool:
    """
    Ask Claude whether two discrepancy findings refer to the same UI issue.
    Uses temperature=0.0 for deterministic binary decision.
    Returns True if same issue, False if different.
    """
    prompt = f"""You are comparing two UI discrepancy findings to determine
if they refer to the same UI element and the same issue.

Finding A:
- Element: {candidate.get('element_name', '')}
- Type: {candidate.get('discrepancy_type', '')}
- Description: {candidate.get('description', '')}

Finding B:
- Element: {group.get('element_name', '')}
- Type: {group.get('discrepancy_type', '')}
- Description: {group.get('description', '')}

Do these two findings refer to the same UI discrepancy on the same UI element?
Respond with only a single word: YES or NO."""

    try:
        response = client.messages.create(
            model=model,
            max_tokens=10,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}]
        )
        answer = response.content[0].text.strip().upper()
        print(f"[CI Semantic] '{candidate.get('element_name')}' vs "
              f"'{group.get('element_name')}' → {answer}")
        return answer == "YES"

    except Exception as e:
        print(f"[CI Semantic] Claude grouping failed: {e} "
              f"— falling back to lexical similarity")
        return _lexical_similarity(
            candidate.get("element_name", ""),
            group["element_name"]
        ) >= 0.72


def _find_canonical_group(
    candidate: Dict,
    canonical_groups: List[Dict],
    client: anthropic.Anthropic,
    model: str,
) -> int:
    """
    Find the index of an existing canonical group this candidate belongs to.
    Uses two-stage approach:
      Stage 1 — fast lexical pre-filter (no API call)
      Stage 2 — Claude semantic confirmation (API call only if needed)
    Returns -1 if no match found.
    """
    for idx, group in enumerate(canonical_groups):
        # Stage 1 — fast pre-filter
        if not _quick_prefilter(candidate, group):
            continue

        # Stage 2 — Claude semantic confirmation
        if _are_same_discrepancy(client, candidate, group, model):
            return idx

    return -1


def _is_self_contradicting(finding: Dict) -> bool:
    """
    Detect findings where Claude's own description contradicts
    its classification — e.g. description says 'no discrepancy exists'
    but it was still reported as a finding.

    Returns True if the finding should be discarded.
    """
    description = finding.get("description", "").lower()
    element = finding.get("element_name", "").lower()
    criterion = finding.get("violated_criterion", "").lower()

    # Check description for self-contradiction phrases
    combined_text = description + " " + element + " " + criterion
    return any(
        phrase in combined_text
        for phrase in SELF_CONTRADICTION_PHRASES
    )


def _generate_feedback(discrepancy: Dict) -> str:
    """Generate natural language feedback string for the frontend."""
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


def _build_canonical_ac_rows(canonical_acs: List[Any]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for idx, item in enumerate(canonical_acs or [], start=1):
        if isinstance(item, dict):
            ac_id = item.get("ac_id") or f"AC-{idx:02d}"
            text = item.get("text") or item.get("ac_text") or ""
        else:
            ac_id = f"AC-{idx:02d}"
            text = str(item)
        rows.append({"ac_id": ac_id, "text": text})
    return rows


def _resolve_canonical_requirement_id(
    violated_criterion: str,
    canonical_rows: List[Dict[str, str]],
    threshold: float = CANONICAL_AC_MATCH_THRESHOLD,
) -> str:
    if not canonical_rows:
        return ""

    normalized_violated = _normalize_text(violated_criterion or "")
    if normalized_violated:
        for row in canonical_rows:
            if _normalize_text(row.get("text", "")) == normalized_violated:
                return row.get("ac_id", "")

    best_row = None
    best_score = 0.0
    for row in canonical_rows:
        score = _lexical_similarity(violated_criterion or "", row.get("text", ""))
        if score > best_score:
            best_row = row
            best_score = score

    if best_row and best_score >= threshold:
        return best_row.get("ac_id", "")

    return ""


def compute_confidence_index(
    all_pass_results: List[List[Dict[str, Any]]],
    n_passes: int = 5,
    high_threshold: float = 0.80,
    medium_threshold: float = 0.60,
    canonical_acs: List[Any] = None,
) -> List[Dict[str, Any]]:

    # Initialise Claude client for semantic grouping
    model = os.environ.get("MODULE2_MODEL", "claude-sonnet-4-6")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    canonical_rows = _build_canonical_ac_rows(canonical_acs or [])

    canonical_groups: List[Dict] = []

    for pass_idx, pass_results in enumerate(all_pass_results):
        seen_in_this_pass = set()

        for candidate in pass_results:
            dtype = candidate.get("discrepancy_type", "")
            ename = candidate.get("element_name", "")

            # Validate required fields
            if not ename or not dtype:
                continue
            if dtype not in VALID_DISCREPANCY_TYPES:
                continue

            # Find matching group using semantic grouping
            group_idx = _find_canonical_group(
                candidate, canonical_groups, client, model
            )

            if group_idx == -1:
                # New unique discrepancy — create new canonical group
                new_idx = len(canonical_groups)
                canonical_groups.append({
                    "element_name": ename,
                    "discrepancy_type": dtype,
                    "violated_criterion": candidate.get(
                        "violated_criterion", ""
                    ),
                    "screen_region": candidate.get(
                        "screen_region", "unknown"
                    ),
                    "description": candidate.get("description", ""),
                    "run_count": 1,
                    "contributing_passes": [pass_idx],
                })
                seen_in_this_pass.add((new_idx, pass_idx))
                print(f"[CI] NEW GROUP: '{ename}'")

            else:
                # Existing group — count once per pass
                key = (group_idx, pass_idx)
                if key not in seen_in_this_pass:
                    canonical_groups[group_idx]["run_count"] += 1
                    canonical_groups[group_idx][
                        "contributing_passes"
                    ].append(pass_idx)
                    seen_in_this_pass.add(key)
                    print(f"[CI] MATCHED '{ename}' → group {group_idx} "
                          f"(run_count now "
                          f"{canonical_groups[group_idx]['run_count']})")

    # Print final groups summary
    print(f"\n[CI] Final canonical_groups count: {len(canonical_groups)}")
    for g in canonical_groups:
        ci = g['run_count'] / n_passes
        print(f"  - '{g['element_name']}': "
              f"run_count={g['run_count']}, ci={ci:.2f}")

    # Build results list
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

        fallback_requirement_id = f"AC-{ac_idx + 1:02d}"
        resolved_requirement_id = _resolve_canonical_requirement_id(
            group.get("violated_criterion", ""),
            canonical_rows,
        )

        discrepancy = {
            "requirement_id": resolved_requirement_id or fallback_requirement_id,
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

    # ── Self-Contradiction Filter ────────────────────────────────────
    # Remove findings where Claude's own description contradicts
    # its classification — catches stable hallucinations that the
    # CI threshold cannot filter
    filtered_results = []
    discarded_contradictions = []

    for r in results:
        if _is_self_contradicting(r):
            print(f"[CI] SELF-CONTRADICTION DETECTED — discarding: "
                  f"'{r['element_name']}'")
            print(f"     CI was {r['confidence_index']} "
                  f"({r['confidence_label']}) but description "
                  f"contradicts the finding")
            discarded_contradictions.append(r["element_name"])
        else:
            filtered_results.append(r)

    if discarded_contradictions:
        print(f"\n[CI] Self-contradiction filter removed "
              f"{len(discarded_contradictions)} finding(s):")
        for name in discarded_contradictions:
            print(f"  - '{name}'")

    # Sort by confidence index descending
    filtered_results.sort(
        key=lambda x: x["confidence_index"], reverse=True
    )
    return filtered_results
