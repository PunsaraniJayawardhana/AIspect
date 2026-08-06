from backend.pipeline.module3 import test_generator


def test_template_defect_script_collects_dom_tokens_beyond_body_text():
    discrepancy = {
        "discrepancy_id": "DISC-001",
        "discrepancy_type": "missing_element",
        "description": "The Your Name field is missing",
        "ac_text": "The contact form must include 'Your Name'",
        "violated_criterion": "The contact form must include 'Your Name'",
    }

    script = test_generator._build_template_defect_script(
        discrepancy,
        app_url="http://localhost:5173",
        nav_path="/contact",
    )

    assert "collectLiveUiTokens" in script
    assert "querySelectorAll('*')" in script
    assert "getAttribute('placeholder')" in script
    assert "getAttribute('aria-label')" in script
    assert "getAttribute('data-testid')" in script
    assert "label[for=\\\"${fieldId}\\\"]" in script
    assert "Expected phrase:" in script


def test_mode2_fallback_uses_dom_inventory_template_script():
    discrepancy = {
        "discrepancy_id": "DISC-002",
        "discrepancy_type": "missing_element",
        "description": "The Your Name field is missing",
        "ac_text": "The contact form must include 'Your Name'",
        "priority_rank": 1,
        "tpri_score": 0.75,
    }

    test_case = test_generator._mode2_fallback(
        discrepancy,
        ticket_id="EXC-15",
        app_url="http://localhost:5173",
        nav_path="/contact",
    )

    assert test_case["mode"] == "defect_first"
    assert test_case["cypress_script"]
    assert "collectLiveUiTokens" in test_case["cypress_script"]


def test_template_defect_script_injects_login_when_enabled(monkeypatch):
    monkeypatch.setenv("MODULE3_LOGIN_ENABLED", "true")
    monkeypatch.setenv("MODULE3_LOGIN_URL", "http://localhost:5173/login")
    monkeypatch.setenv("MODULE3_LOGIN_USERNAME", "qa@example.com")
    monkeypatch.setenv("MODULE3_LOGIN_PASSWORD", "secret")
    monkeypatch.setenv("MODULE3_LOGIN_REQUIRED", "false")
    monkeypatch.setenv("MODULE3_LOGIN_USERNAME_SELECTOR", "input[name='email']")
    monkeypatch.setenv("MODULE3_LOGIN_PASSWORD_SELECTOR", "input[name='password']")
    monkeypatch.setenv("MODULE3_LOGIN_SUBMIT_SELECTOR", "button[type='submit']")

    discrepancy = {
        "discrepancy_id": "DISC-003",
        "discrepancy_type": "missing_element",
        "description": "The Your Name field is missing",
        "ac_text": "The contact form must include 'Your Name'",
    }

    script = test_generator._build_template_defect_script(
        discrepancy,
        app_url="http://localhost:5173",
        nav_path="/contact",
    )

    assert "Optional auth bootstrap for protected screens" in script
    assert "cy.visit(loginUrl);" in script
    assert "const requireLogin = false;" in script
    assert "Module3 login skipped: selectors missing" in script
    assert "cy.get('body').then(($body) => {" in script
    assert "type(\"qa@example.com\", { log: false })" in script
    assert "type(\"secret\", { log: false })" in script
    assert "cy.get(resolvedSubmitSelector, { timeout: 10000 }).first().click({ force: true });" in script


def test_template_defect_script_honors_strict_login_mode(monkeypatch):
    monkeypatch.setenv("MODULE3_LOGIN_ENABLED", "true")
    monkeypatch.setenv("MODULE3_LOGIN_REQUIRED", "true")
    monkeypatch.setenv("MODULE3_LOGIN_URL", "http://localhost:5173/login")
    monkeypatch.setenv("MODULE3_LOGIN_USERNAME", "qa@example.com")
    monkeypatch.setenv("MODULE3_LOGIN_PASSWORD", "secret")

    discrepancy = {
        "discrepancy_id": "DISC-005",
        "discrepancy_type": "missing_element",
        "description": "The Your Name field is missing",
        "ac_text": "The contact form must include 'Your Name'",
    }

    script = test_generator._build_template_defect_script(
        discrepancy,
        app_url="http://localhost:5173",
        nav_path="/contact",
    )

    assert "const requireLogin = true;" in script
    assert "throw new Error(message);" in script


def test_template_defect_script_skips_login_by_default(monkeypatch):
    monkeypatch.delenv("MODULE3_LOGIN_ENABLED", raising=False)
    monkeypatch.delenv("MODULE3_LOGIN_USERNAME", raising=False)
    monkeypatch.delenv("MODULE3_LOGIN_PASSWORD", raising=False)

    discrepancy = {
        "discrepancy_id": "DISC-004",
        "discrepancy_type": "missing_element",
        "description": "The Your Name field is missing",
        "ac_text": "The contact form must include 'Your Name'",
    }

    script = test_generator._build_template_defect_script(
        discrepancy,
        app_url="http://localhost:5173",
        nav_path="/contact",
    )

    assert "Optional auth bootstrap for protected screens" not in script
    assert "const loginUrl =" not in script
