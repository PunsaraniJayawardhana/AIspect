# Module 1 → Module 2 Data Contract

This document defines the shape of data that Module 1 produces and Module 2 consumes.
Both teams must update this file before changing field names or types.

## How to generate real examples

Generate a live Module 2 snapshot locally:

```powershell
python -m backend.scripts.export_module2_snapshot EXC-1
python -m backend.scripts.export_module2_snapshot EXC-7
```

This writes to `output/module2_output/{STORY_KEY}.json`.

You need a configured `.env` with Jira credentials and the AIspect 
backend running (the script re-fetches from Jira to populate story_text, 
nav_path, and design images).

## Required fields

| Field | Type | Description |
|---|---|---|
| `story_key` | string | Jira ticket ID (e.g., "EXC-7") |
| `story_text` | string | Natural-language user-story narrative |
| `nav_path` | string | Breadcrumb path (e.g., "Home Page > Sign Up") |
| `screen_type` | string | One of: login, signup, home, listing, detail, form, dashboard, search, checkout, profile, settings, generic |
| `enriched_ACs` | list[string] | Merged explicit + implicit acceptance criteria, each as a testable assertion |
| `design_images_b64` | list[string] | Base64-encoded PNG images (no data-URL prefix), one per attached design |

## Auxiliary fields (provided but optional for Module 2)

| Field | Type | Description |
|---|---|---|
| `explicit_ACs` | list[string] | The original Jira ACs, separately |
| `implicit_ACs` | list[string] | The Module 1-inferred ACs, separately |

## Encoding

All string fields are UTF-8. Open output files in Python with:
\`\`\`python
import json
with open(path, encoding="utf-8") as f:
    data = json.load(f)
\`\`\`

## Edge cases Module 2 must handle

1. **Empty `design_images_b64`** (list is `[]`):
   Module 2 should return an empty discrepancy list with a flag indicating
   `"skipped_no_images": true`. Validation cannot proceed without images.

2. **Empty `enriched_ACs`** (list is `[]`):
   Module 2 should return an empty discrepancy list with a flag indicating
   `"skipped_no_acs": true`. There is nothing to validate against.

3. **Skipped Module 1 stories**:
   If Module 1 returns `{"skipped": true, "reason": "..."}`, the orchestrator does
   not invoke Module 2 at all. Module 2 will never receive a skipped story as input.

## Open questions

These were proposed during the contract design and need confirmation:

- [ ] Are the field names (`enriched_ACs`, `design_images_b64`, etc.) acceptable, or should they be renamed?
- [ ] Are images expected as raw base64 strings, or with a `data:image/png;base64,` prefix?

## Last updated

[Today's date] — initial contract between [Your name] and [Teammate's name]