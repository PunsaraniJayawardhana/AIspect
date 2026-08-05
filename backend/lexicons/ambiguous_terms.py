"""
Ambiguity lexicon for the UVRI G(s) term.

Sourced from established requirements-engineering literature rather than
built ad hoc, so the lexicon's provenance is traceable and defensible:

  - Femmer et al.'s "weak words" resource — imprecise expressions that
    cannot guarantee unambiguous interpretation without further
    quantification (e.g. dimension adjectives needing a concrete value).
  - Fabbrini et al. / QuARS — weak, non-binding modal verbs and
    subjective/vague terms used in linguistic requirement-smell detection.
  - ISO/IEC/IEEE 29148-aligned smell categories — vagueness, subjectivity,
    optionality, non-verifiable terms.

Each category below cites its literature source. A fifth category,
UI_DOMAIN_EXTENSION, holds terms identified through a small corpus study
of this project's own Jira dataset (see backend/scripts/validate_lexicon.py)
and is kept visually separate so the literature-sourced core and the
project-specific extension are never conflated when reporting on this
component.
"""

from typing import Dict, List, Tuple
import re


# ── Category 1: Weak / non-binding modal verbs (Fabbrini et al. / QuARS) ──
WEAK_MODALS: List[str] = [
    "should", "may", "could", "might", "can possibly", "would ideally",
]

# ── Category 2: Vague adjectives / adverbs (Femmer et al. weak words) ──
VAGUE_ADJECTIVES_ADVERBS: List[str] = [
    "appropriate", "appropriately", "user-friendly", "intuitive", "fast", "easy",
    "efficient", "convenient", "reasonable", "clean", "modern",
    "simple", "flexible", "robust", "seamless", "properly", "correctly",
    "nicely", "quickly", "smoothly", "weak",
]

# ── Category 3: Non-verifiable / subjective terms (ISO 29148 smells) ──
NON_VERIFIABLE_TERMS: List[str] = [
    "as needed", "etc.", "and so on", "if necessary", "where applicable",
    "as appropriate", "as required", "if possible", "where possible",
    "to be defined", "to be determined", "tbd", "flag for clarification",
    "not shown in current design",
]

# ── Category 4: Vague quantifiers / comparatives (Femmer et al.) ──
VAGUE_QUANTIFIERS_COMPARATIVES: List[str] = [
    "several", "many", "few", "most", "some", "faster", "better",
    "more", "less", "minimal", "significant", "adequate", "sufficient",
]

# ── Category 5: UI-domain extension (this project's corpus study) ──
# Populate/adjust this list after running backend/scripts/validate_lexicon.py
# against a sample of real ACs from the project's Jira dataset. Keep every
# addition here, not mixed into the categories above, to preserve the
# literature/project provenance split.
UI_DOMAIN_EXTENSION: List[str] = [
    "responsive", "well-styled", "nicely laid out", "visually appealing",
    "properly aligned", "adequately spaced",
]


SOURCE_MAP: Dict[str, str] = {
    "weak_modals": "Fabbrini et al. (QuARS)",
    "vague_adjectives_adverbs": "Femmer et al. weak-words resource",
    "non_verifiable_terms": "ISO/IEC/IEEE 29148 smell categories",
    "vague_quantifiers_comparatives": "Femmer et al. weak-words resource",
    "ui_domain_extension": "Project corpus study (validate_lexicon.py)",
}

LEXICON: Dict[str, List[str]] = {
    "weak_modals": WEAK_MODALS,
    "vague_adjectives_adverbs": VAGUE_ADJECTIVES_ADVERBS,
    "non_verifiable_terms": NON_VERIFIABLE_TERMS,
    "vague_quantifiers_comparatives": VAGUE_QUANTIFIERS_COMPARATIVES,
    "ui_domain_extension": UI_DOMAIN_EXTENSION,
}


def _build_pattern() -> re.Pattern:
    """
    Compile a single regex matching any lexicon term as a whole word/phrase,
    case-insensitive. Longer phrases are ordered first so e.g. "as needed"
    is matched before a bare "needed" would (which isn't in the lexicon,
    but this ordering protects against future overlapping additions).
    """
    all_terms = [t for terms in LEXICON.values() for t in terms]
    all_terms.sort(key=len, reverse=True)
    escaped = [re.escape(t) for t in all_terms]
    pattern = r"\b(" + "|".join(escaped) + r")\b"
    return re.compile(pattern, re.IGNORECASE)


_PATTERN = _build_pattern()


def find_ambiguous_terms(text: str) -> List[str]:
    """Return every lexicon term found in the text (with duplicates, in order)."""
    if not text:
        return []
    return _PATTERN.findall(text)


def count_ambiguous_terms(text: str) -> int:
    """Convenience wrapper returning just the count."""
    return len(find_ambiguous_terms(text))


def category_of(term: str) -> str:
    """Return which lexicon category a matched term belongs to (case-insensitive)."""
    term_lower = term.lower()
    for category, terms in LEXICON.items():
        if term_lower in (t.lower() for t in terms):
            return category
    return "unknown"


def lexicon_summary() -> Tuple[int, Dict[str, int]]:
    """Total term count and per-category counts, for reporting in the thesis."""
    per_category = {cat: len(terms) for cat, terms in LEXICON.items()}
    return sum(per_category.values()), per_category
