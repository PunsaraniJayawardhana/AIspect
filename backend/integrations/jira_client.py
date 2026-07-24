import httpx
import base64
from typing import List, Optional
from backend.config.settings import (
    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, DEFAULT_JIRA_PROJECT_KEY
)

_AUTH_TOKEN = base64.b64encode(
    f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()
).decode()
_HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Basic {_AUTH_TOKEN}",
}


async def fetch_story_keys(project_key: Optional[str] = None) -> List[str]:
    """Return story keys for the given project (falls back to the .env default)."""
    key = project_key or DEFAULT_JIRA_PROJECT_KEY
    if not key:
        raise ValueError("project_key was not provided and no default is configured")

    url = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
    params = {
        "jql": f"project={key} AND issuetype=Story ORDER BY created ASC",
        "fields": "summary",
        "maxResults": 100,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=_HEADERS, params=params)
        response.raise_for_status()
        return [issue["key"] for issue in response.json().get("issues", [])]


async def fetch_single_story(story_key: str) -> dict:
    """Fetch ONE story's full content by key. Works for any project — the
    key itself (e.g. 'EXC-1', 'PROJ-42') already identifies the project."""
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{story_key}"
    params = {"fields": "summary,description,priority,status,attachment"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=_HEADERS, params=params)
        response.raise_for_status()
        issue = response.json()

    attachments = []
    for att in issue["fields"].get("attachment", []) or []:
        attachments.append({
            "id": att.get("id"),
            "filename": att.get("filename"),
            "mime_type": att.get("mimeType", ""),
            "content_url": att.get("content"),
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


async def fetch_attachment_as_base64(content_url: str) -> str:
    """Download a Jira attachment from its content URL and return base64 bytes."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(content_url, headers=_HEADERS)
        response.raise_for_status()
        return base64.b64encode(response.content).decode()


def _project_key_from_story_key(story_key: str) -> str:
    """Derive the project key from a story key like 'EXC-1' -> 'EXC'."""
    return story_key.split("-")[0]


async def create_bug_ticket(
    summary: str,
    description: str,
    parent_story_key: str,
    severity: str,
) -> dict:
    """
    Create a Jira bug ticket in the SAME project as the originating story,
    so bugs for a story in any project land in that project, never in
    whatever DEFAULT_JIRA_PROJECT_KEY happens to be set to.
    """
    project_key = _project_key_from_story_key(parent_story_key)

    url = f"{JIRA_BASE_URL}/rest/api/3/issue"
    payload = {
        "fields": {
            "project": {"key": project_key},
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