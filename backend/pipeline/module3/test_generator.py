import json
import logging
import os
import re
import requests
import subprocess
import tempfile

from backend.pipeline.module3.llm_client import call_llm
from backend.pipeline.module3.tpri import prioritize_discrepancies
from backend.pipeline.module3.input_schema import normalize_acs, adapt_discrepancies

logger = logging.getLogger(__name__)

STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "from", "that", "this",
    "field", "button", "text", "screen", "form",
    "input", "display", "displays", "visible", "prompt", "message", "login",
    "there", "navigate", "navigates",
}

# Screen discovery is generic: match filenames and parent directories against
# screen-type keywords (not per-ticket hardcoded paths). New screen types can
# be supported by extending this dictionary without changing discovery logic.
SCREEN_TYPE_KEYWORDS = {
    "signup": ["signup", "sign_up", "sign-up", "register", "registration"],
    "login": ["login", "log_in", "sign_in", "signin", "auth"],
    "checkout": ["checkout"],
    "cart": ["cart", "basket"],
    "product": ["product", "productdetails", "pdp"],
}

SKIP_DISCOVERY_DIRS = {"node_modules", "dist", "build", "test", "tests", "__tests__"}
COMPONENT_EXTENSIONS = (".jsx", ".tsx")
_COMPONENT_DISCOVERY_CACHE = {}


def _js_literal(value):
    """Return a JavaScript-safe string literal."""
    return json.dumps(value or "")


def _combine_app_url_and_nav_path(app_url, nav_path=""):
    base_url = (app_url or "").strip()
    path = (nav_path or "").strip()

    if not base_url:
        return ""
    if not path:
        return base_url
    if re.match(r"^https?://", path, flags=re.IGNORECASE):
        return path

    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _read_bool_env(name, default=False):
    raw_value = (os.environ.get(name) or "").strip().lower()
    if not raw_value:
        return default
    return raw_value in {"1", "true", "yes", "on"}


def _build_optional_login_steps(app_url):
    login_enabled = _read_bool_env("MODULE3_LOGIN_ENABLED", False)
    username = (os.environ.get("MODULE3_LOGIN_USERNAME") or "").strip()
    password = (os.environ.get("MODULE3_LOGIN_PASSWORD") or "").strip()
    if not login_enabled or not username or not password:
        return ""

    login_url = (
        os.environ.get("MODULE3_LOGIN_URL")
        or _combine_app_url_and_nav_path(app_url, "/login")
        or app_url
        or ""
    ).strip()
    if not login_url:
        return ""

    username_selector = (os.environ.get("MODULE3_LOGIN_USERNAME_SELECTOR") or "input[name='email']").strip()
    password_selector = (os.environ.get("MODULE3_LOGIN_PASSWORD_SELECTOR") or "input[name='password']").strip()
    submit_selector = (os.environ.get("MODULE3_LOGIN_SUBMIT_SELECTOR") or "button[type='submit']").strip()
    success_selector = (os.environ.get("MODULE3_LOGIN_SUCCESS_SELECTOR") or "").strip()
    require_login = _read_bool_env("MODULE3_LOGIN_REQUIRED", False)

    safe_login_url = _js_literal(login_url)
    safe_username = _js_literal(username)
    safe_password = _js_literal(password)
    safe_username_selector = _js_literal(username_selector)
    safe_password_selector = _js_literal(password_selector)
    safe_submit_selector = _js_literal(submit_selector)
    safe_require_login = "true" if require_login else "false"

    lines = [
        "    // Optional auth bootstrap for protected screens.",
        f"    const loginUrl = {safe_login_url};",
        f"    const usernameSelector = {safe_username_selector};",
        f"    const passwordSelector = {safe_password_selector};",
        f"    const submitSelector = {safe_submit_selector};",
        f"    const requireLogin = {safe_require_login};",
        "    const selectFirst = ($root, selectors) => {",
        "      for (const selector of selectors) {",
        "        if (!selector) {",
        "          continue;",
        "        }",
        "        const found = $root.find(selector);",
        "        if (found.length > 0) {",
        "          return selector;",
        "        }",
        "      }",
        "      return null;",
        "    };",
        "    const failOrSkipLogin = (message) => {",
        "      if (requireLogin) {",
        "        throw new Error(message);",
        "      }",
        "      cy.log(message);",
        "    };",
        "    cy.visit(loginUrl);",
        "    cy.get('body', { timeout: 10000 }).should('be.visible');",
        "    cy.get('body').then(($body) => {",
        "      const usernameCandidates = [",
        "        usernameSelector,",
        "        \"input[type='email']\",",
        "        \"input[name='email']\",",
        "        \"input[name='username']\",",
        "        \"input[placeholder='Email']\",",
        "        \"input[placeholder='email']\",",
        "        \"input[placeholder*='mail' i]\",",
        "      ];",
        "      const passwordCandidates = [",
        "        passwordSelector,",
        "        \"input[type='password']\",",
        "        \"input[name='password']\",",
        "        \"input[placeholder='Password']\",",
        "        \"input[placeholder='password']\",",
        "        \"input[placeholder*='pass' i]\",",
        "      ];",
        "      const submitCandidates = [",
        "        submitSelector,",
        "        \"button[type='submit']\",",
        "        \"input[type='submit']\",",
        "        \"button\",",
        "      ];",
        "",
        "      const resolvedUsernameSelector = selectFirst($body, usernameCandidates);",
        "      const resolvedPasswordSelector = selectFirst($body, passwordCandidates);",
        "      let resolvedSubmitSelector = selectFirst($body, submitCandidates);",
        "",
        "      if (!resolvedSubmitSelector) {",
        "        const loginButton = $body.find(\"button, input[type='submit']\").filter((_, el) => {",
        "          const text = ((el.innerText || el.value || '') + '').toLowerCase().trim();",
        "          return /log\\s*in|sign\\s*in/.test(text);",
        "        });",
        "        if (loginButton.length > 0) {",
        "          resolvedSubmitSelector = \"button, input[type='submit']\";",
        "        }",
        "      }",
        "",
        "      if (!resolvedUsernameSelector || !resolvedPasswordSelector || !resolvedSubmitSelector) {",
        "        failOrSkipLogin(`Module3 login skipped: selectors missing (u=${Boolean(resolvedUsernameSelector)}, p=${Boolean(resolvedPasswordSelector)}, s=${Boolean(resolvedSubmitSelector)})`);",
        "        return;",
        "      }",
        f"      cy.get(resolvedUsernameSelector, {{ timeout: 10000 }}).first().clear().type({safe_username}, {{ log: false }});",
        f"      cy.get(resolvedPasswordSelector, {{ timeout: 10000 }}).first().clear().type({safe_password}, {{ log: false }});",
        "",
        "      if (resolvedSubmitSelector === \"button, input[type='submit']\") {",
        "        cy.get(resolvedSubmitSelector, { timeout: 10000 })",
        "          .contains(/log\\s*in|sign\\s*in/i)",
        "          .first()",
        "          .click({ force: true });",
        "      } else {",
        "        cy.get(resolvedSubmitSelector, { timeout: 10000 }).first().click({ force: true });",
        "      }",
        "    });",
    ]

    if success_selector:
        safe_success_selector = _js_literal(success_selector)
        lines.append(f"    cy.get({safe_success_selector}, {{ timeout: 10000 }}).should('be.visible');")

    return "\n".join(lines) + "\n"


def _is_probably_valid_cypress_script(script):
    if not script:
        return False

    stripped = script.strip()
    if not stripped.startswith("describe("):
        return False
    if "it(" not in stripped:
        return False
    if "```" in stripped:
        return False

    return True


def _passes_node_syntax_check(script):
    """Use node --check when available to reject malformed JS before Cypress."""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".cy.js", delete=False, encoding="utf-8") as handle:
            handle.write(script)
            tmp_path = handle.name

        result = subprocess.run(
            ["node", "--check", tmp_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        return result.returncode == 0, (result.stderr or "").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # If Node is unavailable, rely on lightweight structural checks.
        return True, ""
    except Exception:
        return False, ""
    finally:
        try:
            if "tmp_path" in locals() and os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _normalize_acs(acs):
    normalized = []
    for idx, item in enumerate(acs or [], start=1):
        if isinstance(item, dict):
            normalized.append(
                {
                    "ac_id": item.get("ac_id") or f"AC-{idx:02d}",
                    "text": item.get("text") or item.get("ac_text") or "",
                    "type": item.get("type", "explicit"),
                }
            )
            continue

        normalized.append(
            {
                "ac_id": f"AC-{idx:02d}",
                "text": str(item),
                "type": "explicit",
            }
        )
    return normalized


def _clean_markdown(text):
    if not text:
        return ""

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 1)[1]
        if "\n" in cleaned:
            cleaned = cleaned.split("\n", 1)[1]
        cleaned = cleaned.rstrip("`")
    return cleaned.strip()


def _parse_json_response(text, fallback):
    try:
        cleaned = _clean_markdown(text)
        parsed = json.loads(cleaned)
        return parsed
    except Exception:
        return fallback


def _priority_label(tpri_score):
    if tpri_score is None:
        return "Medium"
    if tpri_score >= 0.75:
        return "High"
    if tpri_score >= 0.5:
        return "Medium"
    return "Low"


def _mode1_fallback_rows(ac):
    return [
        {
            "scenario": f"Positive coverage for {ac['text']}",
            "type": "positive",
            "priority": "Medium",
            "steps": [
                "Open the relevant screen",
                f"Exercise the behavior described by {ac['ac_id']}",
                "Confirm the expected result is visible",
            ],
            "expected_result": f"The application satisfies {ac['text']}",
        },
        {
            "scenario": f"Negative coverage for {ac['text']}",
            "type": "negative",
            "priority": "Medium",
            "steps": [
                "Open the relevant screen",
                f"Trigger the invalid or missing condition for {ac['ac_id']}",
                "Confirm the application rejects or blocks the invalid path",
            ],
            "expected_result": f"The application handles the invalid path safely for {ac['text']}",
        },
        {
            "scenario": f"Boundary coverage for {ac['text']}",
            "type": "boundary",
            "priority": "Medium",
            "steps": [
                "Open the relevant screen",
                f"Apply the edge case for {ac['ac_id']}",
                "Confirm the boundary behavior is correct",
            ],
            "expected_result": f"Boundary behavior is correct for {ac['text']}",
        },
    ]


def _build_mode1_records(ac, ticket_id, generated_rows, start_index=1):
    records = []
    for idx, row in enumerate(generated_rows, start=start_index):
        records.append(
            {
                "tc_id": f"TC-M1-{idx:03d}",
                "mode": "coverage_first",
                "ticket_id": ticket_id,
                "ac_id": ac["ac_id"],
                "discrepancy_id": None,
                "requirement_id": None,
                "scenario": row.get("scenario", f"Coverage for {ac['text']}"),
                "priority": row.get("priority", "Medium"),
                "steps": row.get("steps", []),
                "expected_result": row.get("expected_result", f"Coverage for {ac['text']}"),
                "tpri_score": None,
                "priority_rank": None,
                "ci": None,
                "st": None,
                "rc": None,
                "rc_reasoning": None,
                "fs": None,
                "cypress_script": None,
                "passed": None,
                "confirmed_fault": None,
                "jira_ticket": None,
            }
        )
    return records


def _mode2_fallback(discrepancy, ticket_id, app_url, source_hints=None, nav_path=""):
    summary = discrepancy.get("description") or discrepancy.get("ac_text") or "reported discrepancy"
    target_url = _combine_app_url_and_nav_path(app_url, nav_path)
    safe_url = _js_literal(target_url)
    script = _build_template_defect_script(discrepancy, app_url, source_hints=source_hints, nav_path=nav_path)
    syntax_ok, _ = _passes_node_syntax_check(script)
    if not syntax_ok:
        safe_name = _js_literal("Defect check")
        script = (
            f"describe({safe_name}, () => {{\n"
            "  it('loads the target app', () => {\n"
            f"    cy.visit({safe_url});\n"
            "    cy.get('body', { timeout: 10000 }).should('be.visible');\n"
            "  });\n"
            "});\n"
        )

    return {
        "tc_id": f"TC-M2-{discrepancy.get('priority_rank', 1):03d}",
        "mode": "defect_first",
        "ticket_id": ticket_id,
        "ac_id": discrepancy.get("requirement_id") or discrepancy.get("ac_id") or "AC-01",
        "discrepancy_id": discrepancy.get("discrepancy_id"),
        "requirement_id": discrepancy.get("requirement_id"),
        "scenario": f"Verify the live application against {discrepancy.get('ac_text', 'the reported discrepancy')}",
        "priority": _priority_label(discrepancy.get("tpri_score")),
        "steps": [
            "Open the application URL",
            "Navigate to the relevant screen",
            "Check whether the reported discrepancy is present in the live UI",
        ],
        "expected_result": discrepancy.get("description") or "The discrepancy should be detectable in the live application",
        "tpri_score": discrepancy.get("tpri_score"),
        "priority_rank": discrepancy.get("priority_rank"),
        "ci": discrepancy.get("ci"),
        "st": discrepancy.get("st"),
        "rc": discrepancy.get("rc"),
        "rc_reasoning": discrepancy.get("rc_reasoning"),
        "fs": discrepancy.get("fs"),
        "cypress_script": script,
        "script_source": "template",
        "passed": None,
        "confirmed_fault": None,
        "jira_ticket": None,
    }


def _to_phrase(text):
    if not text:
        return ""
    cleaned = re.sub(r"[^a-zA-Z0-9\s'\?]", " ", str(text)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _extract_phrase_from_quotes(text):
    if not text:
        return ""
    double_quoted_matches = re.findall(r'"([^"]{3,80})"', text)
    if double_quoted_matches:
        return re.sub(r"\s+", " ", double_quoted_matches[0]).strip()

    single_quoted_matches = re.findall(r"'([^']*(?:'[a-zA-Z][^']*)*)'", text)
    if single_quoted_matches:
        return re.sub(r"\s+", " ", single_quoted_matches[0]).strip()

    return ""


def _keyword_phrase(text, max_words=4):
    keywords = _distinctive_keywords(text, max_words=max_words)
    return " ".join(keywords)


def _distinctive_keywords(text, max_words=4):
    tokens = re.findall(r"[a-zA-Z0-9]+(?:'[a-zA-Z]+)?", text or "")
    ranked = []
    for idx, token in enumerate(tokens):
        lowered = token.lower()
        if len(lowered) < 3 or lowered in STOPWORDS:
            continue

        has_internal_caps = any(ch.isupper() for ch in token[1:])
        is_capitalized = token[:1].isupper()
        has_digit = any(ch.isdigit() for ch in token)
        is_long = len(lowered) > 4

        # Keep only distinctive candidates rather than early sentence filler words.
        if not (has_internal_caps or is_capitalized or has_digit or is_long):
            continue

        score = 0
        if has_internal_caps:
            score += 5
        if is_capitalized:
            score += 3
        if has_digit:
            score += 2
        if is_long:
            score += 1

        ranked.append((score, -idx, lowered))

    ranked.sort(reverse=True)
    selected = []
    seen = set()
    for _, _, keyword in ranked:
        if keyword in seen:
            continue
        seen.add(keyword)
        selected.append(keyword)
        if len(selected) >= max_words:
            break
    return selected


def _build_expected_phrase(discrepancy):
    # Prefer quoted AC text first because it is usually the exact UI copy.
    quoted = _extract_phrase_from_quotes(discrepancy.get("violated_criterion", ""))
    element = _to_phrase(discrepancy.get("element_name", ""))
    ac_text = _to_phrase(discrepancy.get("ac_text", ""))

    keyword_candidates = []
    keyword_candidates.extend(_distinctive_keywords(ac_text, max_words=3))
    keyword_candidates.extend(_distinctive_keywords(element, max_words=3))
    keyword_candidates.extend(_distinctive_keywords(discrepancy.get("description", ""), max_words=3))

    for candidate in [quoted] + keyword_candidates:
        if candidate and len(candidate) >= 3:
            return candidate
    return "account"
def _build_candidate_phrases(discrepancy, source_hints=None):
    source_hint_candidates = []
    for hint in source_hints or []:
        candidate = _to_phrase(hint)
        if candidate:
            source_hint_candidates.append(candidate)

    quoted_candidates = [
        _extract_phrase_from_quotes(discrepancy.get("violated_criterion", "")),
        _extract_phrase_from_quotes(discrepancy.get("ac_text", "")),
    ]

    keyword_candidates = []
    keyword_candidates.extend(_distinctive_keywords(discrepancy.get("element_name", ""), max_words=3))
    keyword_candidates.extend(_distinctive_keywords(discrepancy.get("ac_text", ""), max_words=3))
    keyword_candidates.extend(_distinctive_keywords(discrepancy.get("description", ""), max_words=3))

    raw_candidates = source_hint_candidates + quoted_candidates + keyword_candidates

    phrases = []
    seen = set()
    for item in raw_candidates:
        norm = (item or "").strip().lower()
        if len(norm) < 3 or norm in seen:
            continue
        seen.add(norm)
        phrases.append(norm)

    if not phrases:
        phrases.append(_build_expected_phrase(discrepancy).strip().lower())

    return phrases[:4]


def _build_template_defect_script(discrepancy, app_url, source_hints=None, nav_path=""):
    summary = discrepancy.get("description") or discrepancy.get("ac_text") or "reported discrepancy"
    dtype = (discrepancy.get("discrepancy_type") or "").strip().lower()
    safe_name = _js_literal(f"Defect check: {summary}")
    target_url = _combine_app_url_and_nav_path(app_url, nav_path)
    safe_url = _js_literal(target_url)
    login_steps = _build_optional_login_steps(app_url)
    candidate_phrases = _build_candidate_phrases(discrepancy, source_hints=source_hints)
    quoted_phrase_candidates = {
        (_extract_phrase_from_quotes(discrepancy.get("violated_criterion", "")) or "").strip().lower(),
        (_extract_phrase_from_quotes(discrepancy.get("ac_text", "")) or "").strip().lower(),
    }
    quoted_phrase_candidates.discard("")

    phrase_candidate = next(
        (item for item in candidate_phrases if item.strip().lower() in quoted_phrase_candidates),
        candidate_phrases[0] if candidate_phrases else "account",
    )
    keyword_candidate = next(
        (item for item in candidate_phrases if item.strip().lower() not in quoted_phrase_candidates),
        candidate_phrases[0] if candidate_phrases else "account",
    )

    # AC wording describes behavior and often differs from literal UI copy.
    # For non-quoted candidates, a single distinctive keyword is more reliable
    # than requiring fabricated multi-word AC phrases to appear verbatim.
    use_phrase_match = phrase_candidate.strip().lower() in quoted_phrase_candidates
    selected_candidate = phrase_candidate if use_phrase_match else keyword_candidate
    selected_candidate_literal = _js_literal(selected_candidate)

    check_label = "phrase" if use_phrase_match else "keyword"
    expected_var = "expectedPhrase" if use_phrase_match else "expectedKeyword"
    assertion = (
        f"    const {expected_var} = {selected_candidate_literal};\n"
        "    const normalize = (value) => (value || '').toString().replace(/\\s+/g, ' ').trim().toLowerCase();\n"
        "    const collectLiveUiTokens = (doc) => {\n"
        "      const tokens = [];\n"
        "      const seen = new Set();\n"
        "      const addToken = (value) => {\n"
        "        const norm = normalize(value);\n"
        "        if (!norm || norm.length < 2 || seen.has(norm)) {\n"
        "          return;\n"
        "        }\n"
        "        seen.add(norm);\n"
        "        tokens.push(norm);\n"
        "      };\n"
        "\n"
        "      const allNodes = Array.from(doc.querySelectorAll('*'));\n"
        "      allNodes.forEach((el) => {\n"
        "        addToken(el.textContent);\n"
        "        addToken(el.getAttribute('aria-label'));\n"
        "        addToken(el.getAttribute('data-testid'));\n"
        "        addToken(el.getAttribute('id'));\n"
        "        addToken(el.getAttribute('name'));\n"
        "        addToken(el.getAttribute('title'));\n"
        "        addToken(el.getAttribute('alt'));\n"
        "        addToken(el.getAttribute('placeholder'));\n"
        "\n"
        "        if (el.matches && el.matches('input, textarea, select')) {\n"
        "          addToken(el.value);\n"
        "          const fieldId = el.getAttribute('id');\n"
        "          if (fieldId) {\n"
        "            doc.querySelectorAll(`label[for=\\\"${fieldId}\\\"]`).forEach((label) => addToken(label.textContent));\n"
        "          }\n"
        "          const parentLabel = el.closest('label');\n"
        "          if (parentLabel) {\n"
        "            addToken(parentLabel.textContent);\n"
        "          }\n"
        "        }\n"
        "      });\n"
        "\n"
        "      return {\n"
        "        haystack: tokens.join('\\n'),\n"
        "        tokenCount: tokens.length,\n"
        "        elementCount: allNodes.length,\n"
        "      };\n"
        "    };\n"
        "\n"
        "    cy.document({ timeout: 10000 }).then((doc) => {\n"
        f"      const expected = normalize({expected_var});\n"
        "      const inventory = collectLiveUiTokens(doc);\n"
        "      const found = inventory.haystack.includes(expected);\n"
        f"      expect(found, `Expected {check_label}: ${{expected}} (scanned ${{inventory.elementCount}} elements / ${{inventory.tokenCount}} tokens)`).to.eq(true);\n"
        "    });\n"
    )

    return (
        f"describe({safe_name}, () => {{\n"
        "  it('validates the live application against the reported discrepancy', () => {\n"
        f"{login_steps}"
        f"    cy.visit({safe_url});\n"
        "    cy.get('body', { timeout: 10000 }).should('be.visible');\n"
        f"{assertion}"
        "  });\n"
        "});\n"
    )


def _screen_keywords(screen_type):
    normalized = (screen_type or "").strip().lower()
    if not normalized:
        return []
    return SCREEN_TYPE_KEYWORDS.get(normalized, [normalized])


def _discover_component_file(app_src_dir, screen_type):
    cache_key = (screen_type or "").strip().lower()
    if cache_key in _COMPONENT_DISCOVERY_CACHE:
        return _COMPONENT_DISCOVERY_CACHE[cache_key]

    if not app_src_dir or not os.path.isdir(app_src_dir):
        _COMPONENT_DISCOVERY_CACHE[cache_key] = None
        return None

    keywords = [item.lower() for item in _screen_keywords(screen_type) if item]
    if not keywords:
        _COMPONENT_DISCOVERY_CACHE[cache_key] = None
        return None

    best_score = 0
    best_path = None
    tie = False

    for root, dirs, files in os.walk(app_src_dir):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DISCOVERY_DIRS]

        root_lower = root.lower()
        for filename in files:
            if not filename.lower().endswith(COMPONENT_EXTENSIONS):
                continue

            filename_lower = filename.lower()
            score = 0
            for keyword in keywords:
                if keyword in filename_lower:
                    score += 2
                if keyword in root_lower:
                    score += 1

            if score <= 0:
                continue

            full_path = os.path.join(root, filename)
            if score > best_score:
                best_score = score
                best_path = full_path
                tie = False
            elif score == best_score:
                tie = True

    if best_score <= 0 or tie:
        _COMPONENT_DISCOVERY_CACHE[cache_key] = None
        return None

    _COMPONENT_DISCOVERY_CACHE[cache_key] = best_path
    return best_path


def _read_component_source(app_src_dir, screen_type):
    try:
        if not app_src_dir:
            logger.info("Component discovery skipped for screen_type=%s: TARGET_APP_SRC_DIR not set", screen_type)
            return ""

        component_file = _discover_component_file(app_src_dir, screen_type)
        if not component_file:
            logger.info(
                "Component discovery found no unique match for screen_type=%s; will fall back to HTTP scraping",
                screen_type,
            )
            return ""

        logger.info("Component discovery matched screen_type=%s to file=%s", screen_type, component_file)
        with open(component_file, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read() or ""
    except Exception:
        logger.info(
            "Component discovery/read failed for screen_type=%s; will fall back to HTTP scraping",
            screen_type,
        )
        return ""


def _extract_source_hints(source_code, max_hints=40):
    if not source_code:
        return []

    attr_matches = re.findall(
        r"(?:data-testid|aria-label|id|alt)\s*=\s*['\"]([^'\"]+)['\"]",
        source_code,
        flags=re.IGNORECASE,
    )

    # Capture visible JSX text nodes between tags while skipping JSX expressions.
    text_matches = re.findall(r">\s*([^<>{}][^<>{}]{0,120}?)\s*<", source_code)

    hints = []
    seen = set()
    for value in attr_matches + text_matches:
        cleaned = re.sub(r"\s+", " ", (value or "")).strip()
        if len(cleaned) < 2:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        hints.append(cleaned)
        if len(hints) >= max_hints:
            break

    return hints


def _repair_script_with_llm(script, app_url, error_message):
    prompt = (
        "You are fixing a Cypress JavaScript syntax issue.\n"
        f"Target URL: {app_url}\n"
        "Return ONLY valid Cypress JavaScript test code, no markdown fences.\n"
        "Keep behavior equivalent and start with describe(.\n\n"
        f"Node reported this error:\n{error_message}\n\n"
        "Script to repair:\n"
        f"{script}"
    )
    repaired = _clean_markdown(call_llm(prompt, temperature=0.0))
    return repaired


def _fetch_dom_snapshot(app_url, timeout=10):
    try:
        response = requests.get(app_url, timeout=timeout)
        response.raise_for_status()
        return response.text or ""
    except Exception:
        return ""


def _extract_dom_hints(html, max_hints=30):
    if not html:
        return []

    matches = re.findall(
        r"(?:data-testid|aria-label|id)\s*=\s*['\"]([^'\"]+)['\"]",
        html,
        flags=re.IGNORECASE,
    )
    hints = []
    seen = set()
    for match in matches:
        value = (match or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        hints.append(value)
        if len(hints) >= max_hints:
            break
    return hints


def generate_coverage_tests(enriched_acs, user_story, ticket_id):
    normalized = _normalize_acs(enriched_acs)
    tests = []
    counter = 1

    for ac in normalized:
        prompt = (
            "You are a QA engineer writing test cases.\n\n"
            f"User Story: {user_story}\n"
            f"Acceptance Criterion ({ac['ac_id']}): {ac['text']}\n\n"
            "Generate test cases covering:\n"
            "1. One POSITIVE test (valid, happy-path scenario)\n"
            "2. One NEGATIVE test (invalid input or missing element)\n"
            "3. One BOUNDARY test where applicable\n\n"
            "Respond ONLY as a JSON array, no markdown fences:\n"
            "[\n"
            "  {\n"
            '    "scenario": "short description of what is tested",\n'
            '    "type": "positive | negative | boundary",\n'
            '    "priority": "High | Medium | Low",\n'
            '    "steps": ["step 1", "step 2", "step 3"],\n'
            '    "expected_result": "what should happen"\n'
            "  }\n"
            "]"
        )

        try:
            response = call_llm(prompt)
            parsed = _parse_json_response(response, [])
            if not isinstance(parsed, list):
                raise ValueError("LLM response was not a JSON array")
            generated = _build_mode1_records(ac, ticket_id, parsed, start_index=counter)
            tests.extend(generated)
            counter += len(generated)
        except Exception as exc:
            logger.warning("Coverage test generation failed for %s: %s", ac["ac_id"], exc)
            generated = _build_mode1_records(ac, ticket_id, _mode1_fallback_rows(ac), start_index=counter)
            tests.extend(generated)
            counter += len(generated)

    return tests


def generate_defect_tests(prioritized_discrepancies, app_url, ticket_id, screen_type=None, nav_path=""):
    tests = []
    target_url = _combine_app_url_and_nav_path(app_url, nav_path)
    script_mode = os.environ.get("MODULE3_DEFECT_SCRIPT_MODE", "template").strip().lower()
    allow_llm = script_mode == "llm"

    source_hints = []
    app_src_dir = (os.environ.get("TARGET_APP_SRC_DIR") or "").strip()
    source_code = _read_component_source(app_src_dir, screen_type)
    if source_code:
        source_hints = _extract_source_hints(source_code, max_hints=40)

    if source_hints:
        logger.info(
            "Using %d source-derived hints for screen_type=%s; HTTP DOM scraping skipped",
            len(source_hints),
            screen_type,
        )
        dom_hints = source_hints
    else:
        logger.info(
            "No source hints for screen_type=%s; falling back to HTTP DOM scraping",
            screen_type,
        )
        dom_hints = _extract_dom_hints(_fetch_dom_snapshot(target_url)) if target_url else []

    dom_hint_block = ""
    if dom_hints:
        dom_hint_block = (
            "Known real selectors found on the live page (use these if relevant, do not "
            "invent selectors not related to these unless none apply):\n"
            f"{chr(10).join(dom_hints)}\n\n"
        )

    for discrepancy in prioritized_discrepancies or []:
        prompt = (
            "You are a Cypress test automation engineer.\n\n"
            f"Application URL: {target_url}\n"
            f"Discrepancy Type: {discrepancy.get('discrepancy_type', 'Unknown')}\n"
            f"Description: {discrepancy.get('description', '')}\n"
            f"UI Location: {discrepancy.get('location', 'Unknown')}\n"
            f"Violated AC: {discrepancy.get('ac_text', discrepancy.get('requirement_id', ''))}\n"
            f"TPRI Score: {discrepancy.get('tpri_score', 0.0)} | Rank: {discrepancy.get('priority_rank', 1)}\n\n"
            "Write a complete Cypress test that navigates to the page and asserts\n"
            "whether the described discrepancy exists in the live application.\n"
            f"{dom_hint_block}"
            "Selector preference: data-testid > aria-label > visible text.\n\n"
            "Respond with raw JavaScript only. No markdown. Start with: describe("
        )

        if not allow_llm:
            tests.append(_mode2_fallback(discrepancy, ticket_id, app_url, source_hints=source_hints, nav_path=nav_path))
            continue

        try:
            response = call_llm(prompt)
            script = _clean_markdown(response)
            if not _is_probably_valid_cypress_script(script):
                raise ValueError("LLM response did not contain a usable Cypress script")

            syntax_ok, error_message = _passes_node_syntax_check(script)
            retries = 0
            while not syntax_ok and retries < 2:
                script = _repair_script_with_llm(script, target_url, error_message)
                if not _is_probably_valid_cypress_script(script):
                    raise ValueError("Repaired LLM script was still invalid")
                syntax_ok, error_message = _passes_node_syntax_check(script)
                retries += 1

            if not _is_probably_valid_cypress_script(script):
                raise ValueError("Repaired LLM script was still invalid")
            if not syntax_ok:
                raise ValueError("LLM Cypress script failed local JavaScript syntax check")

            test = _mode2_fallback(discrepancy, ticket_id, app_url, source_hints=source_hints, nav_path=nav_path)
            test["cypress_script"] = script
            test["script_source"] = "llm"
            tests.append(test)
        except Exception as exc:
            logger.warning("Defect test generation failed for %s: %s", discrepancy.get("discrepancy_id"), exc)
            tests.append(_mode2_fallback(discrepancy, ticket_id, app_url, source_hints=source_hints, nav_path=nav_path))

    return tests


def run_test_generator(
    verified_discrepancies,
    explicit_acs,
    implicit_acs,
    story_text,
    story_key,
    screen_type=None,
    app_url=None,
    nav_path="",
):
    normalized_explicit = normalize_acs(explicit_acs, default_type="explicit", start_index=1)
    normalized_implicit = normalize_acs(
        implicit_acs, default_type="implicit", start_index=len(normalized_explicit) + 1
    )
    all_acs = normalized_explicit + normalized_implicit
    
    adapted_discrepancies = adapt_discrepancies(verified_discrepancies, all_acs)

    prioritized = prioritize_discrepancies(
        adapted_discrepancies,
        all_acs,
        story_text or "Unknown user story",
    )

    for item in adapted_discrepancies:
        print(f"[Module3 DEBUG] requirement_id={item.get('requirement_id')} "
              f"ac_match_score={item.get('ac_match_score')} "
              f"ac_text={item.get('ac_text')[:60]}")

    defect_tests = generate_defect_tests(
        prioritized,
        app_url,
        story_key,
        screen_type=screen_type,
        nav_path=nav_path,
    ) if app_url else []
    coverage_tests = generate_coverage_tests(all_acs, story_text or "Unknown user story", story_key)

    return defect_tests + coverage_tests