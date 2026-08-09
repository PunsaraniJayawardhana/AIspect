"""Generate presentation-ready Module 3 evaluation reports.

This script is read-only with respect to pipeline execution: it consumes already
persisted Module 3 results and existing evaluation/tuning functions.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from statistics import mean
from typing import Dict, Iterable, List, Sequence

from backend.pipeline.module3.evaluate_tpri import evaluate_orderings, load_ticket_results
from backend.pipeline.module3.tune_weights import WEIGHT_KEYS, tune_weights

try:
    from tabulate import tabulate  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    tabulate = None


def _ensure_matplotlib():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "matplotlib is required to generate charts. Install it with 'pip install matplotlib'."
        ) from exc


PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT_ROOT / "output" / "eval"
CHARTS_DIR = OUTPUT_DIR / "charts"
DEFAULT_TICKETS = ("EXC-1", "EXC-2", "EXC-4", "EXC-5", "EXC-7", "EXC-9")
MEAN_APFD_LABEL = "Mean APFD"
EXCLUDED_TICKET_REASONS = {
    # EXC-10 targets an auth-gated screen and its confirmed faults are false positives.
    "EXC-10": "confirmed faults were false positives due to unsupported authenticated screens",
}


def _results_table_headers() -> List[str]:
    return [
        "Ticket",
        "APFD (TPRI)",
        "APFD (AC-order)",
        "APFD (Random-30)",
    ]


def _format_float(value: float, digits: int = 4) -> str:
    return f"{float(value):.{digits}f}"


def _render_table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    if tabulate is not None:
        return tabulate(rows, headers=headers, tablefmt="github", floatfmt=".4f")

    str_rows = [[str(cell) for cell in row] for row in rows]
    str_headers = [str(header) for header in headers]

    widths = [len(item) for item in str_headers]
    for row in str_rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def _fmt_line(parts: Sequence[str]) -> str:
        return "| " + " | ".join(parts[idx].ljust(widths[idx]) for idx in range(len(parts))) + " |"

    header_line = _fmt_line(str_headers)
    separator = "| " + " | ".join("-" * widths[idx] for idx in range(len(widths))) + " |"
    body = [_fmt_line(row) for row in str_rows]
    return "\n".join([header_line, separator] + body)


def _print_table(title: str, headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    print(title)
    print(_render_table(headers, rows))
    print()


def _save_csv(path: Path, headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def _save_markdown(
    path: Path,
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    note_lines: Sequence[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown = _render_table(headers, rows) + "\n"
    if note_lines:
        markdown += "\n" + "\n".join(note_lines) + "\n"
    path.write_text(markdown, encoding="utf-8")


def _load_tests_or_raise(ticket_id: str) -> List[dict]:
    return load_ticket_results(ticket_id)


def _collect_eval_rows(ticket_ids: Iterable[str], random_runs: int, seed: int):
    rows = []
    per_ticket_eval = {}
    exclusions = []
    for ticket_id in ticket_ids:
        excluded_reason = EXCLUDED_TICKET_REASONS.get(ticket_id)
        if excluded_reason:
            exclusions.append({"ticket_id": ticket_id, "reason": excluded_reason})
            continue

        tests = _load_tests_or_raise(ticket_id)
        evaluation = evaluate_orderings(tests, random_runs=random_runs, seed=seed)
        if int(evaluation.get("n_faults", 0)) <= 0:
            exclusions.append(
                {
                    "ticket_id": ticket_id,
                    "reason": "zero confirmed faults, APFD undefined",
                }
            )
            continue

        orderings = evaluation["orderings"]
        tpri_apfd = orderings["tpri"]["apfd"]
        ac_apfd = orderings["ac_declaration"]["apfd"]
        random_apfd = orderings["random"]["apfd"]
        if tpri_apfd is None or ac_apfd is None or random_apfd is None:
            exclusions.append(
                {
                    "ticket_id": ticket_id,
                    "reason": "APFD undefined for one or more orderings",
                }
            )
            continue

        row = {
            "ticket_id": ticket_id,
            "tpri_apfd": float(tpri_apfd),
            "ac_apfd": float(ac_apfd),
            "random_apfd": float(random_apfd),
        }
        rows.append(row)
        per_ticket_eval[ticket_id] = row
    return rows, per_ticket_eval, exclusions


def _build_exclusion_note_lines(exclusions: Sequence[Dict[str, str]]) -> List[str]:
    if not exclusions:
        return []
    parts = [f"{item['ticket_id']} excluded - {item['reason']}." for item in exclusions]
    return ["Note: " + " ".join(parts)]


def _results_table_rows(eval_rows: Sequence[Dict[str, float]]) -> List[List[object]]:
    if not eval_rows:
        raise ValueError("No tickets remain after exclusions; cannot compute APFD averages")

    body = [
        [
            row["ticket_id"],
            _format_float(row["tpri_apfd"]),
            _format_float(row["ac_apfd"]),
            _format_float(row["random_apfd"]),
        ]
        for row in eval_rows
    ]

    average = {
        key: mean([float(row[key]) for row in eval_rows])
        for key in ("tpri_apfd", "ac_apfd", "random_apfd")
    }
    body.append(
        [
            "Average",
            _format_float(average["tpri_apfd"]),
            _format_float(average["ac_apfd"]),
            _format_float(average["random_apfd"]),
        ]
    )
    return body


def refresh_results_table(
    ticket_ids: Iterable[str],
    random_runs: int = 30,
    seed: int = 42,
    output_dir: Path | None = None,
) -> List[List[object]]:
    normalized_ticket_ids = []
    for ticket in ticket_ids:
        ticket_id = str(ticket).strip()
        if ticket_id and ticket_id not in normalized_ticket_ids:
            normalized_ticket_ids.append(ticket_id)

    if not normalized_ticket_ids:
        raise ValueError("At least one valid ticket ID must be provided")

    eval_rows, _, exclusions = _collect_eval_rows(normalized_ticket_ids, random_runs=random_runs, seed=seed)
    table_headers = _results_table_headers()
    table_rows = _results_table_rows(eval_rows)
    note_lines = _build_exclusion_note_lines(exclusions)

    target_output_dir = output_dir or OUTPUT_DIR
    _save_markdown(target_output_dir / "results_table.md", table_headers, table_rows, note_lines=note_lines)
    _save_csv(target_output_dir / "results_table.csv", table_headers, table_rows)
    return table_rows


def _build_tuning_tickets(ticket_ids: Iterable[str]) -> List[dict]:
    tickets = []
    for ticket_id in ticket_ids:
        tests = _load_tests_or_raise(ticket_id)
        fault_ids = [
            str(test.get("tc_id"))
            for test in tests
            if test.get("confirmed_fault") is True and test.get("tc_id")
        ]
        tickets.append(
            {
                "ticket_id": ticket_id,
                "results_path": str(PROJECT_ROOT / "output" / "results" / f"{ticket_id}.json"),
                "fault_test_ids": fault_ids,
            }
        )
    return tickets


def _score_with_weights(tests: Sequence[dict], weights: Dict[str, float]) -> List[dict]:
    ordered_pairs = sorted(
        enumerate(tests),
        key=lambda item: (
            -sum(float(weights.get(key, 0.0)) * float(item[1].get(key, 0.0) or 0.0) for key in WEIGHT_KEYS),
            item[1].get("ac_order_index") if item[1].get("ac_order_index") is not None else item[0],
            item[1].get("tc_id") or "",
        ),
    )
    return [tests[index] for index, _ in ordered_pairs]


def _apfd_from_fault_ids(ordered_tests: Sequence[dict], fault_ids: Sequence[str]) -> float:
    fault_set = {str(item) for item in fault_ids}
    if not ordered_tests:
        return 1.0

    positions = []
    for idx, test in enumerate(ordered_tests, start=1):
        if str(test.get("tc_id") or "") in fault_set:
            positions.append(idx)

    if not positions:
        return 1.0

    n_tests = len(ordered_tests)
    n_faults = len(positions)
    return 1 - (sum(positions) / (n_tests * n_faults)) + (1 / (2 * n_tests))


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(float(weights.get(key, 0.0)) for key in WEIGHT_KEYS)
    if total <= 0:
        uniform = 1.0 / len(WEIGHT_KEYS)
        return dict.fromkeys(WEIGHT_KEYS, uniform)
    return {key: float(weights.get(key, 0.0)) / total for key in WEIGHT_KEYS}


def _zero_and_renormalize(weights: Dict[str, float], zero_key: str) -> Dict[str, float]:
    modified = {key: float(weights.get(key, 0.0)) for key in WEIGHT_KEYS}
    modified[zero_key] = 0.0
    return _normalize_weights(modified)


def _mean_apfd_for_weights(tuning_tickets: Sequence[dict], weights: Dict[str, float]) -> float:
    apfds = []
    for ticket in tuning_tickets:
        tests = _load_tests_or_raise(str(ticket["ticket_id"]))
        fault_ids = [str(item) for item in ticket.get("fault_test_ids") or []]
        ordered = _score_with_weights(tests, weights)
        apfds.append(_apfd_from_fault_ids(ordered, fault_ids))
    return mean(apfds) if apfds else 1.0


def _plot_apfd_comparison(eval_rows: Sequence[Dict[str, float]], output_path: Path) -> None:
    plt = _ensure_matplotlib()

    tickets = [row["ticket_id"] for row in eval_rows]
    tpri_vals = [row["tpri_apfd"] for row in eval_rows]
    ac_vals = [row["ac_apfd"] for row in eval_rows]
    random_vals = [row["random_apfd"] for row in eval_rows]

    indices = list(range(len(tickets)))
    width = 0.25

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar([index - width for index in indices], tpri_vals, width=width, label="TPRI")
    ax.bar(indices, ac_vals, width=width, label="AC-order")
    ax.bar([index + width for index in indices], random_vals, width=width, label="Random")

    ax.set_title("APFD Comparison by Ticket")
    ax.set_xlabel("Ticket")
    ax.set_ylabel("APFD")
    ax.set_xticks(indices)
    ax.set_xticklabels(tickets)
    ax.set_ylim(0, 1.05)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def _plot_ablation(
    ablation_rows: Sequence[Dict[str, float]], baseline_apfd: float, output_path: Path
) -> None:
    plt = _ensure_matplotlib()

    labels = [row["variant"] for row in ablation_rows]
    values = [row["mean_apfd"] for row in ablation_rows]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(labels, values)
    ax.axhline(y=baseline_apfd, linestyle="--", linewidth=1.5, label=f"Baseline ({baseline_apfd:.4f})")

    ax.set_title("Mean APFD by Zeroed Weight Factor")
    ax.set_xlabel("Ablation Variant")
    ax.set_ylabel(MEAN_APFD_LABEL)
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y", alpha=0.3)

    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.01,
            f"{value:.4f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    ax.legend()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def _check_ticket_files(ticket_ids: Sequence[str]) -> None:
    missing = [
        ticket_id
        for ticket_id in ticket_ids
        if not (PROJECT_ROOT / "output" / "results" / f"{ticket_id}.json").exists()
    ]
    if missing:
        missing_str = ", ".join(missing)
        raise FileNotFoundError(
            "Missing required ticket results under output/results: "
            f"{missing_str}. Generate/copy those files before running this report."
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate Module 3 evaluation and tuning report artifacts.")
    parser.add_argument("--tickets", nargs="+", default=list(DEFAULT_TICKETS), help="Ticket IDs to evaluate")
    parser.add_argument("--random-runs", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--step", type=float, default=0.1)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)

    ticket_ids = [str(ticket).strip() for ticket in args.tickets if str(ticket).strip()]
    if not ticket_ids:
        raise ValueError("At least one ticket must be provided")

    _check_ticket_files(ticket_ids)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=== APFD RESULTS ===")
    eval_rows, _, _ = _collect_eval_rows(ticket_ids, random_runs=args.random_runs, seed=args.seed)
    table_headers = _results_table_headers()
    table_rows = refresh_results_table(ticket_ids, random_runs=args.random_runs, seed=args.seed)
    _print_table("", table_headers, table_rows)

    print("=== WEIGHT TUNING ===")
    tuning_tickets = _build_tuning_tickets(ticket_ids)
    tuning_result = tune_weights(tuning_tickets, step=args.step)

    top_k = max(1, int(args.top_k))
    top_candidates = tuning_result["ranked"][:top_k]
    top_headers = ["Rank", MEAN_APFD_LABEL, "CI", "ST", "RC", "FS"]
    top_rows = []
    for index, candidate in enumerate(top_candidates, start=1):
        weights = candidate["weights"]
        top_rows.append(
            [
                index,
                _format_float(candidate["mean_apfd"]),
                _format_float(weights["ci"]),
                _format_float(weights["st"]),
                _format_float(weights["rc"]),
                _format_float(weights["fs"]),
            ]
        )
    _print_table("Top 5 by Mean APFD", top_headers, top_rows)

    ranked = tuning_result["ranked"]
    weight_grid_headers = ["Rank", MEAN_APFD_LABEL, "CI", "ST", "RC", "FS"]
    weight_grid_rows = []
    for index, candidate in enumerate(ranked, start=1):
        weights = candidate["weights"]
        weight_grid_rows.append(
            [
                index,
                _format_float(candidate["mean_apfd"]),
                _format_float(weights["ci"]),
                _format_float(weights["st"]),
                _format_float(weights["rc"]),
                _format_float(weights["fs"]),
            ]
        )
    _save_csv(OUTPUT_DIR / "weight_grid.csv", weight_grid_headers, weight_grid_rows)

    print("=== ABLATION STUDY ===")
    best_weights = _normalize_weights({key: float(tuning_result["best"]["weights"][key]) for key in WEIGHT_KEYS})
    baseline_apfd = _mean_apfd_for_weights(tuning_tickets, best_weights)

    ablation_headers = ["Variant", "CI", "ST", "RC", "FS", MEAN_APFD_LABEL, "Drop vs Baseline"]
    ablation_rows = []
    ablation_chart_rows = []
    for key in WEIGHT_KEYS:
        ablated = _zero_and_renormalize(best_weights, key)
        ablated_mean = _mean_apfd_for_weights(tuning_tickets, ablated)
        drop = baseline_apfd - ablated_mean
        row = [
            f"Zero {key.upper()}",
            _format_float(ablated["ci"]),
            _format_float(ablated["st"]),
            _format_float(ablated["rc"]),
            _format_float(ablated["fs"]),
            _format_float(ablated_mean),
            _format_float(drop),
        ]
        ablation_rows.append(row)
        ablation_chart_rows.append(
            {
                "variant": f"Zero {key.upper()}",
                "mean_apfd": ablated_mean,
                "drop": drop,
            }
        )

    baseline_row = [
        "Full Baseline",
        _format_float(best_weights["ci"]),
        _format_float(best_weights["st"]),
        _format_float(best_weights["rc"]),
        _format_float(best_weights["fs"]),
        _format_float(baseline_apfd),
        _format_float(0.0),
    ]

    _print_table("Baseline + Single-Factor Ablations", ablation_headers, [baseline_row] + ablation_rows)

    _plot_apfd_comparison(eval_rows, CHARTS_DIR / "apfd_comparison.png")
    _plot_ablation(ablation_chart_rows, baseline_apfd, CHARTS_DIR / "ablation_apfd_drop.png")

    print("Artifacts written:")
    print(f"- {OUTPUT_DIR / 'results_table.md'}")
    print(f"- {OUTPUT_DIR / 'results_table.csv'}")
    print(f"- {OUTPUT_DIR / 'weight_grid.csv'}")
    print(f"- {CHARTS_DIR / 'apfd_comparison.png'}")
    print(f"- {CHARTS_DIR / 'ablation_apfd_drop.png'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
