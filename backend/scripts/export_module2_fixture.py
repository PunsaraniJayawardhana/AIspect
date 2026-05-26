import argparse
import asyncio
import json
import sys
from pathlib import Path

from backend.integrations.jira_client import fetch_media_as_base64, fetch_single_story
from backend.pipeline.module1.adf_parser import parse_adf
from backend.pipeline.module2.confidence_index import compute_confidence_index
from backend.pipeline.module2.multipass_validator import run_multipass_validation


DEFAULT_OUTPUT_DIR = Path("backend/scripts/fixtures")


async def export_module2_fixture(story_key: str, output_path: Path | None = None) -> dict:
    story = await fetch_single_story(story_key)

    if story.get("description_adf") is None:
        raise ValueError(f"Story {story_key} has no description ADF payload")

    parsed = parse_adf(story["description_adf"])
    design_images_b64 = []
    for media_uuid in parsed.get("media_uuids", []):
        design_images_b64.append(await fetch_media_as_base64(media_uuid))

    passes = await run_multipass_validation(parsed.get("explicit_ACs", []), design_images_b64)
    verified_discrepancies = compute_confidence_index(passes)

    data = {
        "story_key": story_key,
        "summary": story.get("summary"),
        "priority": story.get("priority"),
        "status": story.get("status"),
        "story_text": parsed.get("story_text"),
        "nav_path": parsed.get("nav_path"),
        "explicit_ACs": parsed.get("explicit_ACs", []),
        "media_uuids": parsed.get("media_uuids", []),
        "design_images_b64": design_images_b64,
        "module2_passes": passes,
        "verified_discrepancies": verified_discrepancies,
    }

    if output_path is None:
        output_path = DEFAULT_OUTPUT_DIR / f"{story_key}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return data


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Export a module 2 fixture for a Jira story.")
    parser.add_argument("story_key", help="Jira story key to export, e.g. EXC-1")
    parser.add_argument(
        "--output",
        help="Optional output path for the JSON fixture. Defaults to backend/scripts/fixtures/<story>.json",
    )
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else None
    result = await export_module2_fixture(args.story_key, output_path)

    print(json.dumps(result, indent=2, sort_keys=True))
    if output_path is None:
        print(f"\nSaved fixture to {DEFAULT_OUTPUT_DIR / f'{args.story_key}.json'}")
    else:
        print(f"\nSaved fixture to {output_path}")

    return 0


def main() -> int:
    try:
        return asyncio.run(main_async())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
