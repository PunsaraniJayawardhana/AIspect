"""
ADF (Atlassian Document Format) parser for AIspect Module 1.

Walks the ADF tree of a Jira user story and extracts:
  - story_text   : the user-story narrative
  - nav_path     : the screen's location in the app (e.g. "Home Page > Sign Up")
  - explicit_ACs : a flat list of acceptance criteria as testable strings
  - media_uuids  : IDs of embedded design images (kept for backward compatibility)

Handles two common AC layouts:
  1. Flat — a single heading-3 "Acceptance criteria" followed by one bulletList.
  2. Hierarchical — a heading-3 "Acceptance criteria" followed by multiple
     heading-4 sub-section titles, each with its own paragraph and bulletList.

Tolerates missing sections by returning empty defaults rather than raising.
"""

from typing import List, Dict, Any, Optional


# ── Low-level text helpers ──────────────────────────────────────────────

def _extract_text(node: Dict[str, Any]) -> str:
    """Recursively pull plain text from any ADF node."""
    if not isinstance(node, dict):
        return ""

    if node.get("type") == "text":
        return node.get("text", "")

    parts: List[str] = []
    for child in node.get("content", []) or []:
        parts.append(_extract_text(child))
    return "".join(parts)


def _paragraph_text(node: Dict[str, Any]) -> str:
    """Return cleaned text from a paragraph node."""
    return _extract_text(node).strip()


# ── Section discovery ──────────────────────────────────────────────────

def _find_section_content(
    doc_content: List[Dict[str, Any]],
    heading_title: str,
) -> List[Dict[str, Any]]:
    """
    Find the nodes that appear between a heading and the next heading
    AT THE SAME LEVEL OR HIGHER. Sub-headings (deeper levels) stay inside
    the section so nested AC structures are preserved.

    Returns a list of ADF nodes belonging to that section, or [] if not found.
    """
    target = heading_title.strip().lower()
    section: List[Dict[str, Any]] = []
    in_section = False
    section_level: Optional[int] = None

    for node in doc_content:
        if node.get("type") == "heading":
            node_level = node.get("attrs", {}).get("level", 1)
            heading_text = _extract_text(node).strip().lower()

            if in_section:
                # Stop only if this heading is at the same level or shallower
                # than our section's heading. Deeper headings are sub-sections.
                if section_level is not None and node_level <= section_level:
                    break
                # Otherwise it's a sub-heading — keep it as part of the section
                section.append(node)
                continue

            if heading_text == target:
                in_section = True
                section_level = node_level
                continue

        elif in_section:
            section.append(node)

    return section


# ── Specific extractors per section ────────────────────────────────────

def _extract_story_text(doc_content: List[Dict[str, Any]]) -> str:
    """Pull the user-story narrative from the 'User story' section."""
    nodes = _find_section_content(doc_content, "User story")
    parts: List[str] = []
    for node in nodes:
        text = _paragraph_text(node)
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def _extract_nav_path(doc_content: List[Dict[str, Any]]) -> str:
    """
    Pull the navigation path from the 'Other information' section.
    Expected format: "Path to access the X feature: Home Page > Sign Up."
    Returns the part after the colon, with trailing punctuation removed.
    """
    nodes = _find_section_content(doc_content, "Other information")
    for node in nodes:
        text = _paragraph_text(node)
        if ":" in text:
            path = text.split(":", 1)[1].strip().rstrip(".")
            return path
    return ""

def _extract_context(doc_content: List[Dict[str, Any]]) -> str:
    """Pull the descriptive context/background from the 'Context' section."""
    nodes = _find_section_content(doc_content, "Context")
    parts: List[str] = []
    for node in nodes:
        text = _paragraph_text(node)
        if text:
            parts.append(text)
    return " ".join(parts).strip()

def _flatten_ac_list(
    list_node: Dict[str, Any],
    parent_text: Optional[str] = None,
) -> List[str]:
    """
    Walk a bulletList recursively and produce a flat list of AC strings.

    Leaf items become ACs. Items with nested lists pass their text as a
    category prefix to child ACs, accumulated with any inherited prefix
    from outer scopes so context is never lost across recursion levels.
    """
    out: List[str] = []
    if not isinstance(list_node, dict):
        return out

    for item in list_node.get("content", []) or []:
        if item.get("type") != "listItem":
            continue

        item_paragraphs: List[str] = []
        nested_lists: List[Dict[str, Any]] = []
        for child in item.get("content", []) or []:
            if child.get("type") == "paragraph":
                item_paragraphs.append(_paragraph_text(child))
            elif child.get("type") == "bulletList":
                nested_lists.append(child)

        item_text = " ".join(p for p in item_paragraphs if p).strip()

        if nested_lists:
            # Build a combined prefix that preserves the outer context.
            # If we have both an inherited prefix and this item's own text,
            # join them with an em-dash so child ACs see the full path.
            if parent_text and item_text:
                combined_prefix = f"{parent_text} — {item_text}"
            elif item_text:
                combined_prefix = item_text
            else:
                combined_prefix = parent_text
            for nl in nested_lists:
                out.extend(_flatten_ac_list(nl, parent_text=combined_prefix))
        else:
            if item_text:
                if parent_text:
                    out.append(f"{parent_text} — {item_text}")
                else:
                    out.append(item_text)

    return out


def _extract_acs(doc_content: List[Dict[str, Any]]) -> List[str]:
    """
    Walk every node inside the 'Acceptance criteria' section and produce
    a flat list of ACs.

    For hierarchical layouts:
      - heading-4 nodes inside the section become sub-section labels
      - paragraph nodes immediately after a sub-section heading act as a
        preamble for the bullets that follow
      - bulletList nodes are flattened and prefixed with the current
        sub-section label

    For flat layouts (no sub-sections):
      - bulletList nodes are flattened with no prefix
    """
    nodes = _find_section_content(doc_content, "Acceptance criteria")
    acs: List[str] = []

    current_subsection: Optional[str] = None
    current_preamble: Optional[str] = None

    for node in nodes:
        node_type = node.get("type")

        if node_type == "heading":
            # A heading inside the AC section is a sub-section title.
            current_subsection = _extract_text(node).strip()
            current_preamble = None
            continue

        if node_type == "paragraph":
            text = _paragraph_text(node)
            if text:
                # A paragraph here is either a sub-section preamble
                # ("Users should see a top navigation bar containing:")
                # or a standalone AC if there's no bullet list after it.
                # We treat it as a preamble; if no bullets follow, we'll
                # surface it as its own AC at the next branching point.
                current_preamble = text
            continue

        if node_type == "bulletList":
            # Decide what prefix to apply to the bullets:
            # - If we have a sub-section and a preamble, prefer the
            #   preamble (it's the more specific local context).
            # - Otherwise fall back to the sub-section label.
            # - Otherwise no prefix.
            prefix: Optional[str] = None
            if current_preamble and current_subsection:
                prefix = f"[{current_subsection}] {current_preamble}"
            elif current_preamble:
                prefix = current_preamble
            elif current_subsection:
                prefix = f"[{current_subsection}]"

            bullets = _flatten_ac_list(node, parent_text=prefix)
            acs.extend(bullets)
            # A preamble is consumed by its following bullet list.
            current_preamble = None
            continue

        # Other node types (tables, codeblocks, mediaSingle, etc.) inside
        # the AC section are ignored for AC extraction.

    return acs


def _extract_media_uuids(doc_content: List[Dict[str, Any]]) -> List[str]:
    """Find every media node anywhere in the doc and return its UUID."""
    uuids: List[str] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "media":
            attrs = node.get("attrs", {}) or {}
            media_id = attrs.get("id")
            if media_id:
                uuids.append(media_id)
        for child in node.get("content", []) or []:
            walk(child)

    for node in doc_content:
        walk(node)

    return uuids


# ── Public entry point ─────────────────────────────────────────────────

def parse_adf(description_adf: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not description_adf or not isinstance(description_adf, dict):
        return {
            "story_text": "",
            "context": "",
            "nav_path": "",
            "explicit_ACs": [],
            "media_uuids": [],
        }

    doc_content = description_adf.get("content", []) or []

    return {
        "story_text": _extract_story_text(doc_content),
        "context": _extract_context(doc_content),
        "nav_path": _extract_nav_path(doc_content),
        "explicit_ACs": _extract_acs(doc_content),
        "media_uuids": _extract_media_uuids(doc_content),
    }
