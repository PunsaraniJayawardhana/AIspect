"""
Anthropic Claude API client wrapper for AIspect.

Centralises model configuration, error handling, and JSON response parsing
so individual modules don't repeat boilerplate.
"""

import json
import re
from typing import Any, List, Dict
from anthropic import AsyncAnthropic, APIError, RateLimitError
from backend.config.settings import ANTHROPIC_API_KEY


# Single shared async client instance
_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


def _strip_json_fences(text: str) -> str:
    """
    Remove Markdown code fences (```json ... ``` or ``` ... ```) that Claude
    sometimes wraps around JSON responses, even when asked not to.
    """
    text = text.strip()
    fence_match = re.match(
        r"^```(?:json)?\s*\n?(.*?)\n?```$",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if fence_match:
        return fence_match.group(1).strip()
    return text


async def call_claude_json(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2048,
    temperature: float = 0.0,
) -> Any:
    """
    Send a text-only prompt to Claude and parse the response as JSON.

    Returns the parsed JSON value (typically a list or dict).
    Raises RuntimeError on API errors or invalid JSON.
    """
    try:
        response = await _client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except RateLimitError as e:
        raise RuntimeError(f"Claude API rate-limit hit: {e}")
    except APIError as e:
        raise RuntimeError(f"Claude API error: {e}")

    raw_text = "".join(
        block.text for block in response.content
        if block.type == "text"
    ).strip()

    cleaned = _strip_json_fences(raw_text)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Claude returned non-JSON response: {e}\n"
            f"Raw text (first 500 chars):\n{raw_text[:500]}"
        )