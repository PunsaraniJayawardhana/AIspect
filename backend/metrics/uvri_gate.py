"""
Runtime UVRI readiness gate.

Given a computed UVRI score for a user story, decide whether the story is
"ready" to enter the UI-validation audit pipeline or should be flagged back to
the author as not meeting the required quality level.

The threshold is calibrated offline (backend/scripts/uvri_threshold_selection.py,
ROC + Youden's J against expert ratings) and stored in
backend/config/uvri_threshold.json. This module loads that value once, with a
safe hard-coded fallback so the gate still works if the config is missing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Fallback used only if the config file is absent/unreadable. Keep it equal to
# the last committed calibration so behaviour is deterministic either way.
DEFAULT_THRESHOLD = 0.721

_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "uvri_threshold.json"


@lru_cache(maxsize=1)
def _load_threshold() -> float:
    try:
        data = json.loads(_CONFIG_PATH.read_text())
        threshold = float(data["threshold"])
        if not (0.0 <= threshold <= 1.0):
            raise ValueError(f"threshold out of range: {threshold}")
        if threshold == 0.0:
            raise ValueError("threshold must be greater than zero")
        return threshold
    except (OSError, ValueError, KeyError):
        return DEFAULT_THRESHOLD


@dataclass(frozen=True)
class ReadinessResult:
    uvri: float
    threshold: float
    is_ready: bool          # True  => acceptable, proceed
    flagged: bool           # True  => below quality bar, warn the author
    margin: float           # uvri - threshold  (negative => how far below the bar)
    message: str


def evaluate_readiness(uvri: float, threshold: float | None = None) -> ReadinessResult:
    """
    Classify a story by its UVRI score.

    Rule: flag as NOT READY when uvri <= threshold (matches the ROC/Youden
    operating point used during calibration).

    Parameters
    ----------
    uvri : float
        The story's UVRI in [0, 1] (use the pre-enrichment score for an
        incoming-story quality gate).
    threshold : float, optional
        Override the calibrated threshold (useful for tests / experiments).
    """
    t = _load_threshold() if threshold is None else float(threshold)
    flagged = uvri <= t
    margin = round(uvri - t, 4)
    if flagged:
        msg = (
            f"Requirement below the UI-validation readiness bar "
            f"(UVRI {uvri:.3f} <= {t:.3f}). Acceptance criteria likely lack "
            f"coverage, specificity, or testability; revise before auditing."
        )
    else:
        msg = f"Requirement meets the readiness bar (UVRI {uvri:.3f} > {t:.3f})."
    return ReadinessResult(
        uvri=round(float(uvri), 4),
        threshold=round(float(t), 4),
        is_ready=not flagged,
        flagged=flagged,
        margin=margin,
        message=msg,
    )


def active_threshold() -> float:
    """Expose the currently loaded threshold (e.g. for logging / API responses)."""
    return _load_threshold()