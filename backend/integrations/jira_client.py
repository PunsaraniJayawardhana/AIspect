import httpx
import base64
from typing import List
import logging
from backend.config.settings import (
    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY
)

_AUTH_TOKEN = base64.b64encode(
    f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()
).decode()
_HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Basic {_AUTH_TOKEN}",
}


async def fetch_story_keys() -> List[str]:
    """Return only the story keys for the configured project."""
    url = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
    params = {
        "jql": f"project={JIRA_PROJECT_KEY} AND issuetype=Story ORDER BY created ASC",
        "fields": "summary",
        "maxResults": 100,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=_HEADERS, params=params)
        response.raise_for_status()
        return [issue["key"] for issue in response.json().get("issues", [])]


# async def fetch_single_story(story_key: str) -> dict:
#     """Fetch ONE story's full content by key. Preserves the raw ADF tree."""
#     url = f"{JIRA_BASE_URL}/rest/api/3/issue/{story_key}"
#     params = {"fields": "summary,description,priority,status,attachment"}

#     async with httpx.AsyncClient(timeout=30.0) as client:
#         response = await client.get(url, headers=_HEADERS, params=params)
#         response.raise_for_status()
#         issue = response.json()

#     return {
#         "id": issue["key"],
#         "summary": issue["fields"]["summary"],
#         "description_adf": issue["fields"].get("description"),
#         "priority": (issue["fields"].get("priority") or {}).get("name"),
#         "status": (issue["fields"].get("status") or {}).get("name"),
#         "attachments": issue["fields"].get("attachment", []),
#     }

async def fetch_single_story(story_key: str) -> dict:
    """Fetch ONE story's full content by key. Preserves the raw ADF tree.

    If Jira environment variables are not configured, attempt to load a
    local fixture from `backend/scripts/fixtures/{story_key}_module1.json`
    and construct a minimal ADF-compatible payload so the orchestrator can
    run end-to-end using fixtures.
    """
    # Prefer local fixtures when available so offline runs work even if
    # Jira env vars are partially configured. This makes testing reliable.
    import os, json
    logger = logging.getLogger(__name__)
    fixture_dir = os.path.join(os.path.dirname(__file__), "..", "scripts", "fixtures")
    fixture_path = os.path.join(fixture_dir, f"{story_key}_module1.json")
    if os.path.exists(fixture_path):
        logger.info("Using local fixture for story %s: %s", story_key, fixture_path)
        with open(fixture_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        # Build a minimal ADF-like tree to satisfy parse_adf()
        story_text = data.get("story_text", "")
        explicit_acs = data.get("explicit_ACs", [])

        content = []
        # User story
        content.append({"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "User story"}]})
        content.append({"type": "paragraph", "content": [{"type": "text", "text": story_text}]})

        # Acceptance criteria
        content.append({"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "Acceptance criteria"}]})
        bullets = {"type": "bulletList", "content": []}
        for ac in explicit_acs:
            # ac may be dict or string
            ac_text = ac.get("text") if isinstance(ac, dict) else str(ac)
            bullets["content"].append({
                "type": "listItem",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": ac_text}]}]
            })
        content.append(bullets)

        return {
            "id": story_key,
            "summary": data.get("story_text", ""),
            "description_adf": {"type": "doc", "content": content},
            "priority": None,
            "status": None,
            "attachments": [],
        }

    # Fallback to live Jira call
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{story_key}"
    params = {"fields": "summary,description,priority,status,attachment"}

    logger.info("Fetching story from Jira API: %s", story_key)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=_HEADERS, params=params)
        response.raise_for_status()
        issue = response.json()

    # Normalise attachments to a simple structure with everything we need.
    attachments = []
    for att in issue["fields"].get("attachment", []) or []:
        attachments.append({
            "id": att.get("id"),
            "filename": att.get("filename"),
            "mime_type": att.get("mimeType", ""),
            "content_url": att.get("content"),  # ready-to-fetch URL
            "size": att.get("size"),
        })

    return {
        "id": issue["key"],
        "summary": issue["fields"]["summary"],
        "description_adf": issue["fields"].get("description"),
        "priority": (issue["fields"].get("priority") or {}).get("name"),
        "status": (issue["fields"].get("status") or {}).get("name"),
        "attachments": attachments,
    }

# async def fetch_media_as_base64(media_uuid: str) -> str:
#     """Download a Figma design image embedded as a media node."""
#     url = f"{JIRA_BASE_URL}/rest/api/3/attachment/content/{media_uuid}"
#     async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
#         response = await client.get(url, headers=_HEADERS)
#         response.raise_for_status()
#         return base64.b64encode(response.content).decode()

async def fetch_attachment_as_base64(content_url: str) -> str:
    """
    Download a Jira attachment from its content URL and return base64 bytes.
    The content URL comes directly from the ticket's attachments array.
    """
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(content_url, headers=_HEADERS)
        response.raise_for_status()
        return base64.b64encode(response.content).decode()

async def create_bug_ticket(
    summary: str,
    description: str,
    parent_story_key: str,
    severity: str,
) -> dict:
    """Create a Jira bug ticket linked to the originating user story."""
    url = f"{JIRA_BASE_URL}/rest/api/3/issue"
    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": summary,
            "issuetype": {"name": "Bug"},
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    },
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Originating story: "},
                            {
                                "type": "text",
                                "text": parent_story_key,
                                "marks": [{
                                    "type": "link",
                                    "attrs": {
                                        "href": f"{JIRA_BASE_URL}/browse/{parent_story_key}"
                                    },
                                }],
                            },
                        ],
                    },
                ],
            },
            "labels": [f"aispect-{severity.lower()}", "auto-generated"],
        }
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            url,
            headers={**_HEADERS, "Content-Type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        return response.json()