import json
import logging
import re

from backend.config.settings import CI_HIGH_THRESHOLD
from backend.pipeline.module3.llm_client import call_llm

logger = logging.getLogger(__name__)

SEVERITY_LOOKUP = {
    "Missing_Element": 1.0,
    "Business_Rule_Violation": 0.9,
    "Interaction_Flow_Error": 0.7,
    "Wrong_Label": 0.6,
    "Layout_Constraint_Mismatch": 0.4,
}


def _clean_json_payload(text):
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 1)[1]
        if "\n" in cleaned:
            cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rstrip("`")
    cleaned = cleaned.strip()
    return cleaned


def get_rc_score(ac_text, user_story):
    fallback = {
        "rc_score": 0.5,
        "reasoning": "LLM provider unavailable; using neutral RC fallback.",
    }

    prompt = (
        "You are a senior QA analyst evaluating the business criticality "
        "of an acceptance criterion for a software feature.\n\n"
        f"User Story: {user_story}\n"
        f"Acceptance Criterion: {ac_text}\n\n"
        "Score this acceptance criterion on a scale of 0.0 to 1.0 based on:\n"
        "1. CENTRALITY: How central is this to the core business value?\n"
        "2. DEPENDENCY: Would the user story fail entirely without this?\n"
        "3. PROTECTION: Does this protect user data or core workflow?\n\n"
        "Respond ONLY in this exact JSON format with no other text:\n"
        '{"rc_score": 0.0, "reasoning": "one sentence explanation referencing the AC"}'
    )

    try:
        text = call_llm(prompt, max_tokens=200, temperature=0.0)
        cleaned = _clean_json_payload(text)
        if not cleaned:
            raise ValueError("LLM response did not contain JSON")

        data = json.loads(cleaned)
        rc_score = max(0.0, min(1.0, float(data.get("rc_score", 0.5))))
        reasoning = str(data.get("reasoning", "LLM produced a neutral RC reasoning."))
        return {"rc_score": rc_score, "reasoning": reasoning}
    except Exception as exc:
        logger.warning("RC scoring failed; using fallback: %s", exc)
        return fallback


def compute_fs(ac_text, all_acs):
    if not all_acs or len(all_acs) <= 1:
        return 0.0

    target = _token_set(ac_text)
    related = 0
    for other in all_acs:
        if other == ac_text:
            continue
        other_set = _token_set(other)
        if not target or not other_set:
            continue
        union = target.union(other_set)
        if not union:
            continue
        jaccard = len(target.intersection(other_set)) / len(union)
        if jaccard > 0.20:
            related += 1

    return related / max(1, len(all_acs) - 1)


def _token_set(text):
    tokens = re.findall(r"[a-z0-9]+", str(text).lower())
    return set(tokens)


def _severity_score(discrepancy_type):
    return SEVERITY_LOOKUP.get(discrepancy_type, 0.5)


def compute_tpri(ci, discrepancy_type, ac_text, user_story, all_acs, weights=None):
    weights = weights or {"ci": 0.25, "st": 0.25, "rc": 0.25, "fs": 0.25}
    rc_info = get_rc_score(ac_text, user_story)
    st = _severity_score(discrepancy_type)
    fs = compute_fs(ac_text, all_acs)
    rc = rc_info["rc_score"]

    alpha = float(weights.get("ci", 0.25))
    beta = float(weights.get("st", 0.25))
    gamma = float(weights.get("rc", 0.25))
    delta = float(weights.get("fs", 0.25))

    total = alpha + beta + gamma + delta
    if total == 0:
        alpha = beta = gamma = delta = 0.25
        total = 1.0

    score = (alpha * float(ci) + beta * st + gamma * rc + delta * fs) / total
    return {
        "ci": round(float(ci), 4),
        "st": round(st, 4),
        "rc": round(rc, 4),
        "fs": round(fs, 4),
        "rc_reasoning": rc_info["reasoning"],
        "tpri_score": round(score, 4),
    }


def prioritize_discrepancies(discrepancies, enriched_acs, user_story, weights=None):
    prioritized = []
    ac_texts = [
        item.get("text") if isinstance(item, dict) else str(item)
        for item in enriched_acs
    ]

    for discrepancy in discrepancies or []:
        ci = float(discrepancy.get("confidence_index", 0.0))
        confidence_label = str(discrepancy.get("confidence_label", "")).upper()
        if confidence_label != "HIGH" and ci < CI_HIGH_THRESHOLD:
            continue

        tpri = compute_tpri(
            ci=ci,
            discrepancy_type=discrepancy.get("discrepancy_type", "Wrong_Label"),
            ac_text=discrepancy.get("ac_text", discrepancy.get("requirement_id", "")),
            user_story=user_story,
            all_acs=ac_texts,
            weights=weights,
        )
        item = dict(discrepancy)
        item.update(tpri)
        prioritized.append(item)

    prioritized.sort(key=lambda item: (item["tpri_score"], item.get("confidence_index", 0.0)), reverse=True)
    for rank, item in enumerate(prioritized, start=1):
        item["priority_rank"] = rank

    return prioritized
