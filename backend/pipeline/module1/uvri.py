async def compute_uvri(acs: list, screen_type: str) -> tuple[float, dict]:
    """TODO: Implement the 4-term UVRI formula. Stub returns deterministic values."""
    n = len(acs)
    sub = {
        "coverage": min(1.0, n / 8),
        "specificity": 0.6,
        "ambiguity": 0.85,
        "testability": 0.75,
    }
    uvri = 0.25 * sum(sub.values())
    return uvri, sub