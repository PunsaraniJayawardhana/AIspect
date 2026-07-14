import json
import os
import base64
import anthropic
from typing import List, Dict, Any
from .validation_prompts import SYSTEM_PROMPT, VALIDATION_PROMPT_VARIANTS

TEMPERATURE_SCHEDULE = [0.0, 0.3, 0.5, 0.7, 1.0]


def _detect_media_type(img_b64: str) -> str:
    """Detect real image format from base64 header bytes."""
    header = base64.b64decode(img_b64[:16])
    if header[:2] == b'\xff\xd8':
        return "image/jpeg"
    if header[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if header[:6] in (b'GIF87a', b'GIF89a'):
        return "image/gif"
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return "image/webp"
    return "image/jpeg"  # safe default


def run_single_pass(
    client: anthropic.Anthropic,
    criteria: List[str],
    design_images: List[str],
    variant_index: int,
    model: str,
) -> List[Dict[str, Any]]:
    criteria_text = "\n".join(f"- {c}" for c in criteria)
    prompt_text = VALIDATION_PROMPT_VARIANTS[variant_index].format(criteria=criteria_text)
    temperature = TEMPERATURE_SCHEDULE[variant_index]

    content = []
    for img_b64 in design_images:
        media_type = _detect_media_type(img_b64)  # auto-detect instead of hardcoded
        print(f"[Module2] Detected image format: {media_type}")
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": img_b64,
            }
        })
    content.append({"type": "text", "text": prompt_text})

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            temperature=temperature,
        )

        raw_text = response.content[0].text.strip()
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]

        return json.loads(raw_text)

    except (json.JSONDecodeError, IndexError, anthropic.APIError) as e:
        print(f"[Module2] Pass {variant_index + 1} failed: {e}")
        return []


async def run_multipass_validation(
    enriched_ACs: List[str],
    design_images_b64: List[str],
    n: int = 5,
) -> List[List[Dict[str, Any]]]:

    model = os.environ.get("MODULE2_MODEL", "claude-sonnet-4-6")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    all_pass_results = []
    for i in range(n):
        variant_idx = i % len(VALIDATION_PROMPT_VARIANTS)
        print(f"[Module2] Running validation pass {i + 1}/{n} "
              f"(variant={variant_idx + 1}, temp={TEMPERATURE_SCHEDULE[variant_idx]})")

        result = run_single_pass(
            client, enriched_ACs, design_images_b64, variant_idx, model
        )
        print(f"[Module2] Pass {i + 1} found {len(result)} discrepancy candidate(s)")
        all_pass_results.append(result)

    return all_pass_results