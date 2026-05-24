"""
Export a Module 1 result as a clean Module 2 input fixture.

Usage:
    python -m backend.scripts.export_module2_fixture EXC-7

The output is written to backend/output/module2_fixtures/{story_key}.json
and contains only the fields Module 2 needs.
"""

import json
import pathlib
import sys


SOURCE_DIR = pathlib.Path("backend/output/results")
OUTPUT_DIR = pathlib.Path("backend/output/module2_fixtures")


def _read_result_file(source_path: pathlib.Path) -> dict:
    """Read a JSON result file, tolerating both UTF-8 and Windows cp1252."""
    try:
        return json.loads(source_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        # Fallback for files written with Windows default encoding
        return json.loads(source_path.read_text(encoding="cp1252"))


def export_fixture(story_key: str) -> pathlib.Path:
    source_path = SOURCE_DIR / f"{story_key}.json"
    if not source_path.exists():
        raise FileNotFoundError(
            f"No Module 1 result found at {source_path}. "
            f"Run the pipeline for {story_key} first."
        )

    data = _read_result_file(source_path)

    if data.get("skipped"):
        raise ValueError(
            f"{story_key} was skipped during processing "
            f"(reason: {data.get('reason', 'unknown')}). "
            f"Cannot produce a Module 2 fixture from a skipped story."
        )

    # The Module 2 contract: only the fields Module 2 actually needs.
    fixture = {
        "story_key": data["story_key"],
        "story_text": _load_story_text(story_key),
        "nav_path": _load_nav_path(story_key),
        "screen_type": data["screen_type"],
        "explicit_ACs": data["explicit_ACs"],
        "implicit_ACs": data["implicit_ACs"],
        "enriched_ACs": data["explicit_ACs"] + data["implicit_ACs"],
        "design_images_b64": _load_design_images(story_key),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{story_key}.json"
    out_path.write_text(
        json.dumps(fixture, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return out_path


def _load_story_text(story_key: str) -> str:
    """Load story_text by re-fetching from Jira and parsing the ADF."""
    import asyncio
    from backend.integrations.jira_client import fetch_single_story
    from backend.pipeline.module1.adf_parser import parse_adf

    story = asyncio.run(fetch_single_story(story_key))
    parsed = parse_adf(story["description_adf"])
    return parsed["story_text"]


def _load_nav_path(story_key: str) -> str:
    """Load nav_path the same way as story_text."""
    import asyncio
    from backend.integrations.jira_client import fetch_single_story
    from backend.pipeline.module1.adf_parser import parse_adf

    story = asyncio.run(fetch_single_story(story_key))
    parsed = parse_adf(story["description_adf"])
    return parsed["nav_path"]


def _load_design_images(story_key: str) -> list:
    """Re-fetch design images for the fixture."""
    import asyncio
    from backend.integrations.jira_client import (
        fetch_single_story,
        fetch_attachment_as_base64,
    )

    async def gather():
        story = await fetch_single_story(story_key)
        image_attachments = [
            a for a in story["attachments"]
            if a.get("mime_type", "").startswith("image/")
        ]
        return [
            await fetch_attachment_as_base64(a["content_url"])
            for a in image_attachments
        ]

    return asyncio.run(gather())


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m backend.scripts.export_module2_fixture STORY_KEY")
        sys.exit(1)

    story_key = sys.argv[1]
    try:
        out_path = export_fixture(story_key)
        print(f"Wrote Module 2 fixture: {out_path}")
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()