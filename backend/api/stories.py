from fastapi import APIRouter
import httpx
import base64
import traceback
from backend.config.settings import (
    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY
)
from backend.integrations.jira_client import fetch_story_keys

router = APIRouter(prefix="/api/stories", tags=["stories"])


@router.get("")
async def list_stories():
    """Return all story keys for the configured Jira project."""
    keys = await fetch_story_keys()
    return {"stories": keys}


@router.get("/debug")
async def debug_stories():
    """Diagnostic endpoint — shows raw Jira response, no parsing."""
    try:
        auth_token = base64.b64encode(
            f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()
        ).decode()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {auth_token}",
        }

        url = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
        # No issuetype filter — return ANY issue in the project
        params = {
            "jql": f"project={JIRA_PROJECT_KEY}",
            "fields": "summary,issuetype,status",
            "maxResults": 50,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers, params=params)

        # Return raw response without any parsing assumptions
        try:
            body = response.json()
        except Exception:
            body = response.text

        return {
            "project_key_used": JIRA_PROJECT_KEY,
            "jira_url_called": str(response.request.url),
            "status_code": response.status_code,
            "raw_response": body,
        }
    except Exception as e:
        return {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc(),
        }

@router.get("/debug2")
async def debug_direct_fetch():
    """Bypass search — fetch EXC-1 directly to test permissions."""
    try:
        auth_token = base64.b64encode(
            f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()
        ).decode()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {auth_token}",
        }

        # Direct issue fetch — no search involved
        url = f"{JIRA_BASE_URL}/rest/api/3/issue/EXC-1"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)

        # Also fetch /myself to confirm which account the token belongs to
        myself_url = f"{JIRA_BASE_URL}/rest/api/3/myself"
        async with httpx.AsyncClient(timeout=30.0) as client:
            myself_response = await client.get(myself_url, headers=headers)

        return {
            "direct_issue_fetch": {
                "url": url,
                "status_code": response.status_code,
                "body": response.json() if response.status_code == 200 else response.text,
            },
            "token_belongs_to": myself_response.json() if myself_response.status_code == 200 else myself_response.text,
        }
    except Exception as e:
        import traceback
        return {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc(),
        }

@router.get("/debug-adf/{story_key}")
async def debug_adf(story_key: str):
    """Show the raw ADF tree of a specific story for parser development."""
    try:
        auth_token = base64.b64encode(
            f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()
        ).decode()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Basic {auth_token}",
        }
        url = f"{JIRA_BASE_URL}/rest/api/3/issue/{story_key}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers)
        
        issue = response.json()
        return {
            "key": issue["key"],
            "summary": issue["fields"]["summary"],
            "description_adf": issue["fields"].get("description"),
            "attachments": [
                {"id": a["id"], "filename": a["filename"]}
                for a in issue["fields"].get("attachment", [])
            ],
        }
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@router.get("/debug-claude")
async def debug_claude():
    """Verify the Anthropic API key works."""
    try:
        from backend.integrations.claude_client import call_claude_json
        from backend.config.settings import MODULE1_MODEL

        result = await call_claude_json(
            model=MODULE1_MODEL,
            system_prompt="You return only JSON arrays. No explanations.",
            user_prompt='Return a JSON array containing exactly the string "AIspect is alive".',
            max_tokens=100,
            temperature=0.0,
        )
        return {
            "model_used": MODULE1_MODEL,
            "claude_response": result,
            "status": "ok",
        }
    except Exception as e:
        import traceback
        return {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc(),
        }