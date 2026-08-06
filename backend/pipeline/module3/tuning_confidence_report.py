"""Summarize confidence in TPRI weight tuning outcomes.

This script is read-only: it loads an evaluation config, runs the existing
grid search in memory, and prints a compact report showing:
- top-K weight settings
- APFD spread across all candidates
- whether the top result is unique or tied
"""

import argparse
import json
from pathlib import Path

from backend.pipeline.module3.tune_weights import tune_weights


def _load_tickets(config_path):
    payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("tickets"), list):
        return payload["tickets"]
    if isinstance(payload, list):
        return payload
    raise ValueError("Config must be a list or an object containing a 'tickets' list")


def _round_value(value, digits=6):
    return round(float(value), digits)


def classify_confidence(report, strong_margin=0.01, weak_margin=0.001):
    candidate_count = int(report.get("candidate_count", 0))
    top_tie_count = int(report.get("top_tie_count", 0))
    margin = float(report.get("best_margin_over_second", 0.0))
    spread = float(report.get("apfd_spread_best_minus_worst", 0.0))

    if candidate_count == 0:
        return {
            "label": "no_candidates",
            "message": "No candidate weights were evaluated.",
        }

    if top_tie_count == candidate_count or spread <= 0.0:
        return {
            "label": "fully_tied",
            "message": "Fully tied: current data cannot distinguish any weight settings.",
        }

    if top_tie_count == 1 and margin >= strong_margin:
        return {
            "label": "strong_winner",
            "message": "Strong winner: best weights clearly outperform the next candidate.",
        }

    if margin >= weak_margin:
        return {
            "label": "weak_winner",
            "message": "Weak winner: best weights are slightly better; validate with more labeled tickets.",
        }

    return {
        "label": "near_tie",
        "message": "Near tie: differences are too small to trust without more data.",
    }


def build_confidence_report(config_path, step=0.1, top_k=5, tie_tolerance=1e-12):
    tickets = _load_tickets(config_path)
    search = tune_weights(tickets, step=step)

    ranked = search["ranked"]
    best = ranked[0]
    worst = ranked[-1]

    best_score = float(best["mean_apfd"])
    ties = [item for item in ranked if abs(float(item["mean_apfd"]) - best_score) <= tie_tolerance]

    top_items = ranked[: max(1, int(top_k))]
    second_best_score = float(ranked[1]["mean_apfd"]) if len(ranked) > 1 else best_score

    report = {
        "config_path": str(config_path),
        "ticket_count": search["ticket_count"],
        "step": step,
        "candidate_count": len(ranked),
        "best_mean_apfd": _round_value(best_score),
        "best_weights": best["weights"],
        "best_margin_over_second": _round_value(best_score - second_best_score),
        "apfd_spread_best_minus_worst": _round_value(best_score - float(worst["mean_apfd"])),
        "top_is_tie": len(ties) > 1,
        "top_tie_count": len(ties),
        "top_tied_weights": [item["weights"] for item in ties],
        "top_k": [
            {
                "rank": idx + 1,
                "mean_apfd": _round_value(item["mean_apfd"]),
                "weights": item["weights"],
            }
            for idx, item in enumerate(top_items)
        ],
    }
    report["confidence_signal"] = classify_confidence(report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create confidence summary for TPRI weight tuning.")
    parser.add_argument("config", help="Path to tuning config JSON")
    parser.add_argument("--step", type=float, default=0.1)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--tie-tolerance", type=float, default=1e-12)
    parser.add_argument("--signal-only", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    report = build_confidence_report(
        config_path=args.config,
        step=args.step,
        top_k=args.top_k,
        tie_tolerance=args.tie_tolerance,
    )

    if args.signal_only:
        signal = report["confidence_signal"]
        print(
            "{label}: {message}".format(
                label=signal.get("label", "unknown"),
                message=signal.get("message", ""),
            )
        )
        return None

    print(json.dumps(report, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return None


if __name__ == "__main__":
    main()