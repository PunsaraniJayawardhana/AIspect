import json
import logging
import os

logger = logging.getLogger(__name__)

FIXTURE_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts", "fixtures")
USE_MODULE_FIXTURES = os.getenv("USE_MODULE_FIXTURES", "true").lower() == "true"


def _is_stub_acs(acs):
    if not acs:
        return True

    for item in acs:
        text = item if isinstance(item, str) else str(item.get("text", ""))
        lowered = text.lower()
        if any(
            phrase in lowered
            for phrase in (
                "email address",
                "password field",
                "confirm password",
                "submit button",
                "stub story text",
            )
        ):
            return True
    return False


def _is_stub_story_text(story_text, nav_path):
    lowered = " ".join(filter(None, [story_text or "", nav_path or ""])).lower()
    return "stub story text" in lowered or "home page > sign up" in lowered


def _load_json(path):
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        logger.warning("Unable to load fixture %s: %s", path, exc)
        return None


def get_module1_inputs(story_key, explicit_acs, implicit_acs, story_text, nav_path):
    if not USE_MODULE_FIXTURES or not _is_stub_acs(explicit_acs) and not _is_stub_acs(implicit_acs) and not _is_stub_story_text(story_text, nav_path):
        return explicit_acs, implicit_acs, story_text, nav_path

    fixture_path = os.path.join(FIXTURE_ROOT, f"{story_key}_module1.json")
    payload = _load_json(fixture_path)
    if not payload:
        logger.warning("Fixture file not found for %s; using current Module 1 inputs", story_key)
        return explicit_acs, implicit_acs, story_text, nav_path

    logger.info("Using Module 1 fixture for %s", story_key)
    return (
        payload.get("explicit_ACs", explicit_acs),
        payload.get("implicit_ACs", implicit_acs),
        payload.get("story_text", story_text),
        payload.get("nav_path", nav_path),
    )


def get_module2_inputs(story_key, verified_discrepancies):
    if not USE_MODULE_FIXTURES or not _is_stub_discrepancies(verified_discrepancies):
        return verified_discrepancies

    fixture_path = os.path.join(FIXTURE_ROOT, f"{story_key}_module2.json")
    payload = _load_json(fixture_path)
    if not payload:
        logger.warning("Fixture file not found for %s; using current Module 2 inputs", story_key)
        return verified_discrepancies

    logger.info("Using Module 2 fixture for %s", story_key)
    return payload.get("verified_discrepancies", verified_discrepancies)


def _is_stub_discrepancies(discrepancies):
    return not discrepancies
