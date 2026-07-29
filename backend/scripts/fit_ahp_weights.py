"""
backend/scripts/fit_ahp_weights.py

Derives UVRI's four term weights via the Analytic Hierarchy Process (AHP),
from one or more raters' filled-in copies of the AHP Pairwise Comparison
workbook. For each rater file, reads the auto-computed "Value (auto)"
column, builds the 4x4 reciprocal comparison matrix, solves for the
principal eigenvector (priority weights), and computes the Consistency
Ratio (CR) to flag any rater whose judgments were internally inconsistent.

Individual rater matrices are then combined via the geometric mean of
corresponding entries (standard AHP practice for aggregating multiple
experts' judgments -- Aczel & Saaty, 1983), and the aggregated matrix is
solved the same way to produce the final weights.

The comparison table's header row is located dynamically (searching for
"Comparison" / "Your Selection" cells), rather than assumed to be at a
fixed row number -- this makes the script robust to rater files that have
a different number of instruction rows above the table (e.g. some raters'
copies may have extra pasted-in instruction text pushing the table down).

Usage:
    python -m backend.scripts.fit_ahp_weights rater1.xlsx rater2.xlsx rater3.xlsx
"""

import sys
import numpy as np
from openpyxl import load_workbook

LABELS = ["Coverage", "Specificity", "Ambiguity", "Testability"]
RI_TABLE = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12}  # Saaty's random index

SHEET_NAME = "AHP Pairwise Comparison"
HEADER_LABEL_COL_A = "Comparison"
HEADER_LABEL_COL_D = "Your Selection"
VALUE_COLUMN = 5  # column E: "Value (auto -- do not edit)"
N_COMPARISONS = 6  # Coverage-Specificity, Coverage-Ambiguity, Coverage-Testability,
                    # Specificity-Ambiguity, Specificity-Testability, Ambiguity-Testability
MAX_SCAN_ROWS = 60  # how far down to search for the header row


def find_header_row(ws) -> int:
    """Locate the row containing the table header, regardless of how many
    instruction rows precede it in a given rater's copy of the file."""
    for r in range(1, MAX_SCAN_ROWS):
        if (ws.cell(row=r, column=1).value == HEADER_LABEL_COL_A
                and ws.cell(row=r, column=4).value == HEADER_LABEL_COL_D):
            return r
    raise ValueError(
        f"Could not find the comparison table header (looking for "
        f"'{HEADER_LABEL_COL_A}' in column A and '{HEADER_LABEL_COL_D}' in "
        f"column D) within the first {MAX_SCAN_ROWS} rows. Check the file "
        f"hasn't had its header text edited or removed."
    )


def read_rater_values(path: str) -> list:
    """Extract the 6 auto-computed pairwise values from one rater's file."""
    wb = load_workbook(path, data_only=True)
    if SHEET_NAME not in wb.sheetnames:
        raise ValueError(f"{path}: sheet '{SHEET_NAME}' not found")
    ws = wb[SHEET_NAME]

    header_row = find_header_row(ws)

    values = []
    for i in range(N_COMPARISONS):
        row = header_row + 1 + i
        cell = ws.cell(row=row, column=VALUE_COLUMN)
        if cell.value is None or cell.value == "":
            raise ValueError(
                f"{path}: row {row}, column {VALUE_COLUMN} is empty -- "
                f"this rater has not completed all {N_COMPARISONS} comparisons."
            )
        values.append(float(cell.value))
    return values


def build_matrix(vals: list) -> np.ndarray:
    """Build the 4x4 reciprocal matrix from the 6 pairwise values.
    Order: 0=Coverage, 1=Specificity, 2=Ambiguity, 3=Testability."""
    cs, cg, ct, sg, st, gt = vals
    M = np.ones((4, 4))
    M[0, 1] = cs; M[1, 0] = 1 / cs
    M[0, 2] = cg; M[2, 0] = 1 / cg
    M[0, 3] = ct; M[3, 0] = 1 / ct
    M[1, 2] = sg; M[2, 1] = 1 / sg
    M[1, 3] = st; M[3, 1] = 1 / st
    M[2, 3] = gt; M[3, 2] = 1 / gt
    return M


def eigen_weights_and_cr(M: np.ndarray):
    """Principal eigenvector (normalised) + Consistency Ratio."""
    n = M.shape[0]
    eigvals, eigvecs = np.linalg.eig(M)
    idx = np.argmax(eigvals.real)
    lam_max = eigvals.real[idx]
    w = np.abs(eigvecs[:, idx].real)
    w = w / w.sum()
    CI = (lam_max - n) / (n - 1)
    RI = RI_TABLE[n]
    CR = CI / RI if RI > 0 else 0.0
    return w, lam_max, CI, CR


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m backend.scripts.fit_ahp_weights rater1.xlsx [rater2.xlsx ...]")
        sys.exit(1)

    rater_paths = sys.argv[1:]
    matrices = []

    print("=" * 70)
    print("PER-RATER RESULTS")
    print("=" * 70)
    for path in rater_paths:
        vals = read_rater_values(path)
        M = build_matrix(vals)
        matrices.append(M)

        w, lam_max, CI, CR = eigen_weights_and_cr(M)
        status = "OK (CR<0.10)" if CR < 0.10 else "INCONSISTENT (CR>=0.10) -- consider re-rating"
        print(f"\n{path}:")
        print("  weights: " + ", ".join(f"{l}={v:.4f}" for l, v in zip(LABELS, w)))
        print(f"  lambda_max={lam_max:.4f}  CI={CI:.4f}  CR={CR:.4f}  {status}")

    print()
    print("=" * 70)
    print("AGGREGATED ACROSS ALL RATERS (geometric mean of matrices)")
    print("=" * 70)
    agg_M = np.ones((4, 4))
    for i in range(4):
        for j in range(4):
            agg_M[i, j] = np.prod([M[i, j] for M in matrices]) ** (1 / len(matrices))

    w_agg, lam_max_agg, CI_agg, CR_agg = eigen_weights_and_cr(agg_M)
    status_agg = "OK (CR<0.10)" if CR_agg < 0.10 else "INCONSISTENT (CR>=0.10)"

    print("\nAggregated matrix:")
    print(np.round(agg_M, 4))
    print()
    print("Final aggregated weights:")
    for l, v in zip(LABELS, w_agg):
        print(f"  {l:<14}: {v:.4f}")
    print(f"\nlambda_max={lam_max_agg:.4f}  CI={CI_agg:.4f}  CR={CR_agg:.4f}  {status_agg}")

    print()
    print("Suggested .env values:")
    print(f"  UVRI_WEIGHT_COVERAGE={w_agg[0]:.4f}")
    print(f"  UVRI_WEIGHT_SPECIFICITY={w_agg[1]:.4f}")
    print(f"  UVRI_WEIGHT_AMBIGUITY={w_agg[2]:.4f}")
    print(f"  UVRI_WEIGHT_TESTABILITY={w_agg[3]:.4f}")


if __name__ == "__main__":
    main()