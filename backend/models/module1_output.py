# backend/models/module1_output.py

from dataclasses import dataclass
from typing import List

@dataclass
class Module1Output:
    """
    Formal handoff contract from Module 1 to Module 2.
    Module 2 validates enriched_ACs (explicit + implicit merged) against
    the design images, so that both stated-requirement violations (e.g.
    design shows a different field than the story specifies) and
    QA-convention gaps (elements Module 1 inferred as missing) are both
    checked. explicit_ACs and implicit_ACs are kept separately here too,
    for UVRI scoring and for reporting which category any given
    discrepancy traces back to.
    """
    screen_type: str
    enriched_ACs: List[str]        # what Module 2 actually validates against the design
    explicit_ACs: List[str]        # kept for UVRI + provenance tracking
    implicit_ACs: List[str]        # kept for UVRI + provenance tracking
    design_images_b64: List[str]
