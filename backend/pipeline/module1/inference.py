async def infer_implicit_elements(parsed: dict, screen_type: str) -> list:
    """TODO: Real impl calls Claude. Stub returns canned elements."""
    if screen_type == "signup":
        return [
            "Form should display a 'Forgot password' link",
            "Password field should include a show/hide toggle",
            "Email field should have a placeholder text",
        ]
    return []