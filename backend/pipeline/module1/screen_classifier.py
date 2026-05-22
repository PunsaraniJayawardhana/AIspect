async def classify_screen_type(parsed: dict) -> str:
    """TODO: Real impl uses nav_path + LLM. Stub returns based on keywords."""
    path = parsed.get("nav_path", "").lower()
    if "sign up" in path or "register" in path:
        return "signup"
    if "sign in" in path or "login" in path:
        return "login"
    return "generic_form"