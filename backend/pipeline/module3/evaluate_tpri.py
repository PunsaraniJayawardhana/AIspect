"""Read-only Module 3 evaluation harness.

This module evaluates already-executed Module 3 test results by re-sorting the
stored results in memory. It does not invoke Cypress, the LLM, or any other
pipeline step.
"""

import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "output" / "results"


def compute_apfd(fault_first_positions, n):
    """Compute APFD from 1-based fault positions and total test count.

    The implementation follows the standard APFD equation:

        APFD = 1 - (sum(TF_i) / (n * m)) + 1 / (2n)

    where TF_i are the 1-based positions of the first test that reveals each
    fault.
    """

    if n <= 0:
        return 1.0

    positions = [int(position) for position in fault_first_positions or [] if int(position) > 0]
    if not positions:
        return 1.0

    m = len(positions)
    return 1 - (sum(positions) / (n * m)) + (1 / (2 * n))


def compute_ttff(ordered_results):
    """Compute the 1-based position of the first confirmed fault.

    When no fault is present, return ``n + 1`` as a worst-case sentinel so the
    metric stays numeric and can be averaged across random shuffles.
    """

    results = list(ordered_results or [])
    for index, result in enumerate(results, start=1):
        if _is_confirmed_fault(result):
            return float(index)
    return float(len(results) + 1)


def _is_confirmed_fault(result):
    return bool(result.get("confirmed_fault") is True)


def _fault_positions_for_order(ordered_results):
    positions = []
    for index, result in enumerate(ordered_results or [], start=1):
        if _is_confirmed_fault(result):
            positions.append(index)
    return positions


def _fallback_order_index(result, fallback_index):
    ac_order_index = result.get("ac_order_index")
    if ac_order_index is not None:
        return ac_order_index

    priority_rank = result.get("priority_rank")
    if priority_rank is not None:
        return priority_rank

    return fallback_index


def _normalize_tests(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        tests = payload.get("tests")
        if isinstance(tests, list):
            return tests
    raise ValueError("Expected a list of tests or a JSON object with a 'tests' list")


def _order_by_tpri(results):
    return sorted(
        enumerate(results),
        key=lambda item: (
            -(float(item[1].get("tpri_score") or 0.0)),
            _fallback_order_index(item[1], item[0]),
            item[1].get("tc_id") or "",
        ),
    )


def _order_by_ac(results):
    return sorted(
        enumerate(results),
        key=lambda item: (
            _fallback_order_index(item[1], item[0]),
            item[1].get("tc_id") or "",
        ),
    )


def _materialize_order(results, ordered_pairs):
    return [results[index] for index, _ in ordered_pairs]


def evaluate_orderings(test_results, random_runs=30, seed=42):
    """Evaluate TPRI, AC order, and random shuffles using already-run tests."""

    results = list(test_results or [])
    if random_runs <= 0:
        raise ValueError("random_runs must be greater than zero")

    tpri_ordered = _materialize_order(results, _order_by_tpri(results))
    ac_ordered = _materialize_order(results, _order_by_ac(results))

    random_apfd_values = []
    random_ttff_values = []
    base_random = list(results)
    for run_index in range(random_runs):
        shuffled = _deterministic_shuffle(base_random, seed, run_index)
        random_apfd_values.append(compute_apfd(_fault_positions_for_order(shuffled), len(shuffled)))
        random_ttff_values.append(compute_ttff(shuffled))

    return {
        "n_tests": len(results),
        "n_faults": len(_fault_positions_for_order(tpri_ordered)),
        "orderings": {
            "tpri": {
                "apfd": compute_apfd(_fault_positions_for_order(tpri_ordered), len(tpri_ordered)),
                "ttff": compute_ttff(tpri_ordered),
                "ordered_tc_ids": [item.get("tc_id") for item in tpri_ordered],
            },
            "ac_declaration": {
                "apfd": compute_apfd(_fault_positions_for_order(ac_ordered), len(ac_ordered)),
                "ttff": compute_ttff(ac_ordered),
                "ordered_tc_ids": [item.get("tc_id") for item in ac_ordered],
            },
            "random": {
                "apfd": mean(random_apfd_values) if random_apfd_values else 1.0,
                "ttff": mean(random_ttff_values) if random_ttff_values else float(len(results) + 1),
                "runs": random_runs,
            },
        },
    }


def load_ticket_results(ticket_ref, results_dir=DEFAULT_RESULTS_DIR):
    """Load an already-executed Module 3 results file without running pipeline code."""

    if isinstance(ticket_ref, dict):
        if "tests" in ticket_ref:
            return _normalize_tests(ticket_ref)
        ticket_id = ticket_ref.get("ticket_id") or ticket_ref.get("story_key")
        results_path = ticket_ref.get("results_path")
        if results_path:
            return load_ticket_results(results_path, results_dir=results_dir)
        if ticket_id:
            return load_ticket_results(ticket_id, results_dir=results_dir)
        raise ValueError("Ticket reference must include tests, ticket_id, or results_path")

    path = Path(ticket_ref)
    if path.suffix.lower() != ".json" and not path.exists():
        path = Path(results_dir) / f"{ticket_ref}.json"

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    return _normalize_tests(payload)


def _deterministic_shuffle(items, seed, run_index):
    decorated = []
    for index, item in enumerate(items):
        payload = (
            f"{seed}:{run_index}:{index}:"
            f"{item.get('tc_id', '')}:{item.get('ac_order_index', '')}:{item.get('priority_rank', '')}"
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        decorated.append((digest, item))

    decorated.sort(key=lambda pair: pair[0])
    return [item for _, item in decorated]


def _format_summary(ticket_id, evaluation):
    orderings = evaluation["orderings"]
    return {
        "ticket_id": ticket_id,
        "n_tests": evaluation["n_tests"],
        "n_faults": evaluation["n_faults"],
        "tpri_apfd": orderings["tpri"]["apfd"],
        "tpri_ttff": orderings["tpri"]["ttff"],
        "ac_apfd": orderings["ac_declaration"]["apfd"],
        "ac_ttff": orderings["ac_declaration"]["ttff"],
        "random_apfd": orderings["random"]["apfd"],
        "random_ttff": orderings["random"]["ttff"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate existing Module 3 results read-only.")
    parser.add_argument(
        "results",
        nargs="+",
        help="Ticket IDs or paths to JSON files under output/results/",
    )
    parser.add_argument("--random-runs", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    summaries = []
    for item in args.results:
        tests = load_ticket_results(item)
        evaluation = evaluate_orderings(tests, random_runs=args.random_runs, seed=args.seed)
        ticket_id = Path(item).stem if Path(item).suffix.lower() == ".json" else str(item)
        summaries.append(_format_summary(ticket_id, evaluation))

    output = summaries[0] if len(summaries) == 1 else summaries
    print(json.dumps(output, indent=2 if args.pretty else None, sort_keys=args.pretty))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())