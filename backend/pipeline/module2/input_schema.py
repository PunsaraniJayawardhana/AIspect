# backend/pipeline/module2/input_schema.py
from dataclasses import dataclass, field
from typing import List

@dataclass
class DesignImage:
    filename: str
    base64: str

@dataclass
class Module1Output:
    ticket_id: str
    story_text: str
    navigation_path: str
    enriched_acceptance_criteria: List[str]
    design_images: List[DesignImage]