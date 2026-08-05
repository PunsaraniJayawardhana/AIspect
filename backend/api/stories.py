from fastapi import APIRouter, Query
from typing import Optional
import httpx
import base64
import traceback
from config.settings import (
    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, DEFAULT_JIRA_PROJECT_KEY
)
from backend.integrations.jira_client import fetch_story_keys

router = APIRouter(prefix="/api/stories", tags=["stories"])


@router.get("")
async def list_stories(project_key: Optional[str] = Query(default=None)):
    """
    Return story keys for a given Jira project.
    If project_key is omitted, falls back to DEFAULT_JIRA_PROJECT_KEY (.env).
    """
    key = project_key or DEFAULT_JIRA_PROJECT_KEY
    if not key:
        return {"error": "project_key was not provided and no default is configured"}
    keys = await fetch_story_keys(project_key=key)
    return {"project_key": key, "stories": keys}


@router.get("/debug")
async def debug_stories(project_key: Optional[str] = Query(default=None)):
    """Diagnostic endpoint — shows raw Jira response, no parsing."""
    key = project_key or DEFAULT_JIRA_PROJECT_KEY
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
            "jql": f"project={key}",
            "fields": "summary,issuetype,status",
            "maxResults": 50,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=headers, params=params)

        try:
            body = response.json()
        except Exception:
            body = response.text

        return {
            "project_key_used": key,
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
async def debug_direct_fetch(story_key: str = Query(default="EXC-1")):
    """Bypass search — fetch a specific story directly to test permissions.
    Defaults to EXC-1 for backward compatibility, but accepts any story key
    from any project on this Jira Cloud site via ?story_key=PROJ-1."""
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
        return {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc(),
        }


@router.get("/debug-adf/{story_key}")
async def debug_adf(story_key: str):
    """Show the raw ADF tree of a specific story for parser development.
    Already project-agnostic — story_key carries its own project prefix."""
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
        return {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc(),
        }

@router.get("/debug-uvri/{story_key}")
async def debug_uvri(story_key: str):
    """
    Run the full Module 1 chain (parse -> classify -> UVRI) on a real story
    and return every intermediate value, so you can see exactly where a
    number came from without running Module 2/3 or Cypress.
    """
    try:
        from integrations.jira_client import fetch_single_story
        from pipeline.module1.adf_parser import parse_adf
        from pipeline.module1.screen_classifier import classify_screen_type
        from pipeline.module1.uvri import compute_uvri
        from pipeline.module1.inference import infer_implicit_elements

        story = await fetch_single_story(story_key)
        if story["description_adf"] is None:
            return {"story_key": story_key, "skipped": True, "reason": "null description"}

        parsed = parse_adf(story["description_adf"])
        screen_type = await classify_screen_type(parsed)

        uvri_pre, sub_pre = await compute_uvri(parsed["explicit_ACs"], screen_type)

        implicit_ACs = await infer_implicit_elements(parsed, screen_type)
        enriched_ACs = parsed["explicit_ACs"] + implicit_ACs
        uvri_post, sub_post = await compute_uvri(enriched_ACs, screen_type)

        return {
            "story_key": story_key,
            "screen_type": screen_type,
            "explicit_ACs": parsed["explicit_ACs"],
            "implicit_ACs": implicit_ACs,
            "uvri_pre": uvri_pre,
            "sub_pre": sub_pre,
            "uvri_post": uvri_post,
            "sub_post": sub_post,
            "delta": uvri_post - uvri_pre,
        }
    except Exception as e:
        return {
            "error_type": type(e).__name__,
            "error_message": str(e),
            "traceback": traceback.format_exc(),
        }
