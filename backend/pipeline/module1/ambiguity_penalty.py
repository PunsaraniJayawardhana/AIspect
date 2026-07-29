"""
Ambiguity Penalty — G(s) — UVRI sub-term.

G(s) = 1 - (|ambiguous terms| / total word count)

Pure lexicon/regex matching against backend/lexicons/ambiguous_terms.py.
No LLM call — fully deterministic, per the design in What_is_UVRI.pdf.
"""

from typing import List, Tuple, Dict, Any
from lexicons.ambiguous_terms import find_ambiguous_terms, category_of


def compute_ambiguity_penalty(acs: List[str]) -> Tuple[float, Dict[str, Any]]:
    """
    Returns:
        (ambiguity_score, details) where details contains the total word
        count, the ambiguous terms matched, and which category each fell
        into, for auditability and for the lexicon validation study.
    """
    if not acs:
        return 0.0, {"total_words": 0, "ambiguous_count": 0, "matched_terms": []}

    full_text = " ".join(acs)
    total_words = len(full_text.split())

    if total_words == 0:
        return 0.0, {"total_words": 0, "ambiguous_count": 0, "matched_terms": []}

    matches = find_ambiguous_terms(full_text)
    matched_terms = [{"term": m, "category": category_of(m)} for m in matches]

    ambiguity_score = max(0.0, 1.0 - (len(matches) / total_words))

    return ambiguity_score, {
        "total_words": total_words,
        "ambiguous_count": len(matches),
        "matched_terms": matched_terms,
    }
