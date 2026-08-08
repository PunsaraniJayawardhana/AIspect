from pathlib import Path

import backend.pipeline.module3.generate_eval_report as report
from backend.pipeline.module3.generate_eval_report import _results_table_headers, refresh_results_table


def test_refresh_results_table_is_apfd_only(tmp_path: Path) -> None:
    table_rows = refresh_results_table(["EXC-1"], random_runs=3, seed=42, output_dir=tmp_path)
    headers = _results_table_headers()

    assert headers == [
        "Ticket",
        "APFD (TPRI)",
        "APFD (AC-order)",
        "APFD (Random-30)",
    ]
    assert len(headers) == 4
    assert table_rows[-1][0] == "Average"

    markdown_text = (tmp_path / "results_table.md").read_text(encoding="utf-8")
    csv_text = (tmp_path / "results_table.csv").read_text(encoding="utf-8")

    assert "TTFF" not in markdown_text
    assert "TTFF" not in csv_text
    assert "APFD (TPRI)" in markdown_text


def test_refresh_results_table_excludes_zero_fault_and_exc10(tmp_path: Path, monkeypatch) -> None:
    def fake_load(ticket_id: str):
        return [{"tc_id": f"{ticket_id}-TC-1"}]

    def fake_evaluate_orderings(tests, random_runs=30, seed=42):
        ticket_prefix = str(tests[0]["tc_id"]).split("-TC-")[0]
        if ticket_prefix == "EXC-54":
            return {
                "n_tests": 1,
                "n_faults": 0,
                "orderings": {
                    "tpri": {"apfd": None},
                    "ac_declaration": {"apfd": None},
                    "random": {"apfd": None},
                },
            }
        return {
            "n_tests": 1,
            "n_faults": 1,
            "orderings": {
                "tpri": {"apfd": 0.9},
                "ac_declaration": {"apfd": 0.8},
                "random": {"apfd": 0.7},
            },
        }

    monkeypatch.setattr(report, "_load_tests_or_raise", fake_load)
    monkeypatch.setattr(report, "evaluate_orderings", fake_evaluate_orderings)

    table_rows = refresh_results_table(["EXC-10", "EXC-54", "EXC-1"], output_dir=tmp_path)

    assert [row[0] for row in table_rows] == ["EXC-1", "Average"]

    markdown_text = (tmp_path / "results_table.md").read_text(encoding="utf-8")
    assert "EXC-10" in markdown_text
    assert "EXC-54" in markdown_text
    assert "zero confirmed faults, APFD undefined" in markdown_text
    assert "unsupported authenticated screens" in markdown_text
