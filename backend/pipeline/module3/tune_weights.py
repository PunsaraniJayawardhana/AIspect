"""Grid search TPRI weights using already-executed Module 3 results.

The search is read-only: it loads existing JSON outputs from output/results and
re-sorts the stored test results in memory. It never re-runs Cypress.
"""

import argparse
import json
from pathlib import Path

from backend.pipeline.module3.evaluate_tpri import (
    DEFAULT_RESULTS_DIR,
    compute_apfd,
    load_ticket_results,
)


WEIGHT_KEYS = ("ci", "st", "rc", "fs")


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _score_test(test, weights):
    total = 0.0
    for key in WEIGHT_KEYS:
        total += float(weights.get(key, 0.0)) * _as_float(test.get(key), 0.0)
    return total


def _order_by_weights(results, weights):
    return sorted(
        enumerate(results),
        key=lambda item: (
            -_score_test(item[1], weights),
            _order_fallback_index(item[1], item[0]),
            item[1].get("tc_id") or "",
        ),
    )


def _order_fallback_index(test, fallback_index):
    ac_order_index = test.get("ac_order_index")
    if ac_order_index is not None:
        return ac_order_index

    priority_rank = test.get("priority_rank")
    if priority_rank is not None:
        return priority_rank

    return fallback_index


def _materialize_order(results, ordered_pairs):
    return [results[index] for index, _ in ordered_pairs]


def _fault_positions_from_labels(ordered_results, fault_test_ids):
    fault_ids = {str(item) for item in fault_test_ids or []}
    positions = []
    for index, test in enumerate(ordered_results or [], start=1):
        tc_id = str(test.get("tc_id") or "")
        if tc_id in fault_ids:
            positions.append(index)
    return positions


def _evaluate_ticket(ticket, weights):
    results = load_ticket_results(ticket)
    fault_ids = ticket.get("fault_test_ids") or ticket.get("ground_truth_fault_test_ids") or ticket.get("confirmed_fault_ids")
    ordered = _materialize_order(results, _order_by_weights(results, weights))
    positions = _fault_positions_from_labels(ordered, fault_ids)
    return {
        "ticket_id": ticket.get("ticket_id") or ticket.get("story_key") or ticket.get("results_path") or "unknown",
        "apfd": compute_apfd(positions, len(ordered)),
        "ttff": None,
        "fault_count": len({str(item) for item in fault_ids or []}),
    }


def _grid_values(step):
    if step <= 0:
        raise ValueError("step must be greater than zero")

    units = round(1.0 / step)
    if units <= 0:
        raise ValueError("step is too large for a 0.0-1.0 grid")

    for ci_units in range(units + 1):
        for st_units in range(units - ci_units + 1):
            for rc_units in range(units - ci_units - st_units + 1):
                fs_units = units - ci_units - st_units - rc_units
                yield {
                    "ci": ci_units / units,
                    "st": st_units / units,
                    "rc": rc_units / units,
                    "fs": fs_units / units,
                }


def tune_weights(evaluation_tickets, step=0.1):
    """Search weight combinations that maximize mean APFD across tickets."""

    tickets = list(evaluation_tickets or [])
    if not tickets:
        raise ValueError("evaluation_tickets cannot be empty")

    candidates = []
    for weights in _grid_values(step):
        ticket_scores = [_evaluate_ticket(ticket, weights) for ticket in tickets]
        mean_apfd = sum(item["apfd"] for item in ticket_scores) / len(ticket_scores)
        candidates.append(
            {
                "weights": weights,
                "mean_apfd": mean_apfd,
                "ticket_scores": ticket_scores,
            }
        )

    candidates.sort(
        key=lambda item: (
            item["mean_apfd"],
            -sum(item["weights"].get(key, 0.0) for key in WEIGHT_KEYS),
            item["weights"]["ci"],
            item["weights"]["st"],
            item["weights"]["rc"],
            item["weights"]["fs"],
        ),
        reverse=True,
    )

    return {
        "best": candidates[0],
        "ranked": candidates,
        "step": step,
        "ticket_count": len(tickets),
    }


def _load_tickets_from_config(config_path):
    with Path(config_path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        tickets = payload.get("tickets")
        if isinstance(tickets, list):
            return tickets
    raise ValueError("Config must be a list of tickets or an object with a 'tickets' list")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Grid search Module 3 TPRI weights read-only.")
    parser.add_argument(
        "config",
        help="JSON file describing evaluation tickets, or a ticket file path/ID if using a single ticket",
    )
    parser.add_argument("--step", type=float, default=0.1)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    if config_path.exists():
        evaluation_tickets = _load_tickets_from_config(config_path)
    else:
        evaluation_tickets = [{"ticket_id": args.config, "results_path": f"{DEFAULT_RESULTS_DIR / (args.config + '.json')}"}]

    result = tune_weights(evaluation_tickets, step=args.step)
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())