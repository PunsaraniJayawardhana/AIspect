import logging

from backend.config.settings import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    LLM_PROVIDER,
)

logger = logging.getLogger(__name__)

_USAGE_LOG = []


def _get_provider():
    return (LLM_PROVIDER or "anthropic").lower()


def _extract_anthropic_text(response):
    text = ""
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "text":
            text += block.text
    return text


def _extract_groq_text(response):
    try:
        return response.choices[0].message.content or ""
    except Exception:
        return ""


def _extract_usage(response, provider):
    usage = {
        "provider": provider,
        "model": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }

    model = getattr(response, "model", None)
    if not model:
        model = getattr(response, "id", None)
    usage["model"] = model

    raw_usage = getattr(response, "usage", None)
    if raw_usage is None:
        return usage

    if provider == "groq":
        usage["prompt_tokens"] = getattr(raw_usage, "prompt_tokens", None)
        usage["completion_tokens"] = getattr(raw_usage, "completion_tokens", None)
        usage["total_tokens"] = getattr(raw_usage, "total_tokens", None)
        return usage

    usage["prompt_tokens"] = getattr(raw_usage, "input_tokens", None)
    usage["completion_tokens"] = getattr(raw_usage, "output_tokens", None)
    usage["total_tokens"] = getattr(raw_usage, "total_tokens", None)
    if usage["total_tokens"] is None and usage["prompt_tokens"] is not None and usage["completion_tokens"] is not None:
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return usage


def get_usage_log():
    return list(_USAGE_LOG)


def get_usage_summary():
    total_prompt = 0
    total_completion = 0
    total_tokens = 0
    by_provider = {}

    for item in _USAGE_LOG:
        provider = item.get("provider", "unknown")
        by_provider[provider] = by_provider.get(provider, 0) + 1

        prompt = item.get("prompt_tokens") or 0
        completion = item.get("completion_tokens") or 0
        total = item.get("total_tokens") or (prompt + completion)

        total_prompt += prompt
        total_completion += completion
        total_tokens += total

    return {
        "calls": len(_USAGE_LOG),
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "total_tokens": total_tokens,
        "by_provider": by_provider,
    }


def reset_usage_log():
    _USAGE_LOG.clear()


def get_llm_model():
    provider = _get_provider()
    if provider == "groq":
        return GROQ_MODEL or "llama-3.3-70b-versatile"
    return CLAUDE_MODEL


def call_llm(prompt, max_tokens=1024, temperature=0.0):
    provider = _get_provider()

    if provider == "groq":
        if not GROQ_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not configured")

        try:
            from groq import Groq
        except ImportError as exc:
            raise RuntimeError("Groq SDK is not installed") from exc

        client = Groq(api_key=GROQ_API_KEY)
        response = client.chat.completions.create(
            model=get_llm_model(),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = _extract_groq_text(response)
        if not text:
            raise RuntimeError("Groq returned an empty response")
        usage = _extract_usage(response, "groq")
        usage["prompt_tokens"] = usage["prompt_tokens"] or 0
        usage["completion_tokens"] = usage["completion_tokens"] or 0
        usage["total_tokens"] = usage["total_tokens"] or (usage["prompt_tokens"] + usage["completion_tokens"])
        _USAGE_LOG.append(usage)
        logger.info("LLM usage: provider=%s model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s", usage["provider"], usage["model"], usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"])
        return text

    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("Anthropic SDK is not installed") from exc

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=get_llm_model(),
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    text = _extract_anthropic_text(response)
    if not text:
        raise RuntimeError("Anthropic returned an empty response")
    usage = _extract_usage(response, "anthropic")
    usage["prompt_tokens"] = usage["prompt_tokens"] or 0
    usage["completion_tokens"] = usage["completion_tokens"] or 0
    usage["total_tokens"] = usage["total_tokens"] or (usage["prompt_tokens"] + usage["completion_tokens"])
    _USAGE_LOG.append(usage)
    logger.info("LLM usage: provider=%s model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s", usage["provider"], usage["model"], usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"])
    return text
