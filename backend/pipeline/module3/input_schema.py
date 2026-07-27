import re
from difflib import SequenceMatcher

MATCH_THRESHOLD = 0.45

# Module 2's discrepancy_type values are space-separated Title Case
# (see confidence_index.SEVERITY_MAP). Normalize any underscored variants
# (e.g. leftover from earlier fixtures) so every downstream lookup uses
# ONE canonical spelling.
def normalize_discrepancy_type(dtype):
    if not dtype:
        return "Wrong Label"
    return dtype.replace("_", " ").strip()


def _normalize_text(text):
    return re.sub(r"[^a-z0-9\s]", "", str(text).lower()).strip()


def _similarity(a, b):
    return SequenceMatcher(None, _normalize_text(a), _normalize_text(b)).ratio()


def normalize_acs(acs, default_type="explicit", start_index=1):
    normalized = []
    for offset, item in enumerate(acs or []):
        idx = start_index + offset
        if isinstance(item, dict):
            normalized.append({
                "ac_id": item.get("ac_id") or f"AC-{idx:02d}",
                "text": item.get("text") or item.get("ac_text") or "",
                "type": item.get("type", default_type),
            })
        else:
            normalized.append({
                "ac_id": f"AC-{idx:02d}",
                "text": str(item),
                "type": default_type,
            })
    return normalized


def resolve_requirement_id(violated_criterion, normalized_acs):
    """Match a discrepancy's violated_criterion text back to the real
    Module 1 AC it refers to. Returns (ac_id, ac_text, match_score)."""
    best_idx, best_score = -1, 0.0
    for idx, ac in enumerate(normalized_acs):
        score = _similarity(violated_criterion, ac["text"])
        if score > best_score:
            best_idx, best_score = idx, score

    if best_idx == -1 or best_score < MATCH_THRESHOLD:
        return None, violated_criterion, best_score

    matched = normalized_acs[best_idx]
    return matched["ac_id"], matched["text"], best_score


def adapt_discrepancy(discrepancy, normalized_acs):
    """Convert a raw Module 2 discrepancy into what tpri.py / test_generator.py
    need: real requirement_id, real ac_text, canonical discrepancy_type.
    All original fields (ci, confidence_label, element_name, severity, ...) pass through."""
    violated = discrepancy.get("violated_criterion", "")
    ac_id, ac_text, match_score = resolve_requirement_id(violated, normalized_acs)

    adapted = dict(discrepancy)
    adapted["requirement_id"] = ac_id  # None if no confident match — see note below
    adapted["ac_text"] = ac_text or violated
    adapted["discrepancy_type"] = normalize_discrepancy_type(discrepancy.get("discrepancy_type"))
    adapted["ac_match_score"] = round(match_score, 3)

    # discrepancy_id never exists upstream — Module 3 needs a stable one for
    # tc_id generation and Jira bug cross-referencing.
    if not adapted.get("discrepancy_id"):
        tag = (adapted["requirement_id"] or "UNMATCHED")
        elem = re.sub(r"\W+", "", discrepancy.get("element_name", "x"))[:12]
        adapted["discrepancy_id"] = f"{tag}-{elem}"
    return adapted


def adapt_discrepancies(discrepancies, normalized_acs):
    return [adapt_discrepancy(d, normalized_acs) for d in discrepancies or []]