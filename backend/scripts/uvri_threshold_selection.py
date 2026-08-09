"""
UVRI readiness-threshold finder (full functionality, self-contained).

Given a labelled spreadsheet with pre-enrichment sub-metrics and expert_rating,
this finds the UVRI cutoff below which a user story is flagged "not ready for
UI-validation", using ROC + Youden's J. It also reports:
  - AUC and the full ROC operating point,
  - a threshold sweep table (see the precision/recall trade-off),
  - a bootstrap confidence interval for the threshold and AUC (honesty about
    small sample size),
  - the confusion matrix at the chosen cutoff,
and writes the result to a JSON config the runtime gate can read.

Run:
    python -m backend.scripts.uvri_threshold_selection Book3.xlsx
    python -m backend.scripts.uvri_threshold_selection Book3.xlsx --cutoff 2.5 --phase pre
    python -m backend.scripts.uvri_threshold_selection Book3.xlsx --bootstrap 5000
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import auc, confusion_matrix, roc_curve

# Locked AHP weights (Coverage, Specificity, Ambiguity, Testability).
# If you already expose these from fit_ahp_weights.py, import them here instead.
WEIGHTS = {"cov": 0.0697, "spec": 0.3154, "amb": 0.1685, "test": 0.4464}
REQUIRED = ["expert_rating"]

# Where the runtime gate reads the calibrated threshold from.
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "uvri_threshold.json"


def compute_uvri(df: pd.DataFrame, phase: str) -> pd.Series:
    cols = [f"{m}_{phase}" for m in ("cov", "spec", "amb", "test")]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(f"Missing sub-metric columns for phase '{phase}': {missing}")
    return (WEIGHTS["cov"] * df[f"cov_{phase}"]
            + WEIGHTS["spec"] * df[f"spec_{phase}"]
            + WEIGHTS["amb"] * df[f"amb_{phase}"]
            + WEIGHTS["test"] * df[f"test_{phase}"])


def load(path: str | Path) -> pd.DataFrame:
    df = pd.read_excel(path)
    df.columns = [c.strip() for c in df.columns]     # tolerate 'amb_post ' etc.
    for c in REQUIRED:
        if c not in df.columns:
            raise KeyError(f"Column '{c}' not found. Have: {list(df.columns)}")
    return df.dropna(subset=REQUIRED).reset_index(drop=True)


def youden_threshold(uvri: np.ndarray, y: np.ndarray) -> tuple[float, float, int]:
    """Return (threshold, auc, index). Rule: flag when uvri <= threshold."""
    fpr, tpr, thr = roc_curve(y, -uvri)          # low uvri predicts positive ('not ready')
    roc_auc = auc(fpr, tpr)
    j = tpr - fpr
    k = int(np.argmax(j))
    return float(-thr[k]), float(roc_auc), k


def metrics_at(uvri: np.ndarray, y: np.ndarray, t: float) -> dict:
    pred = (uvri <= t).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    sens = tp / (tp + fn) if (tp + fn) else 0.0
    spec = tn / (tn + fp) if (tn + fp) else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * prec * sens / (prec + sens) if (prec + sens) else 0.0
    return dict(tp=int(tp), fp=int(fp), fn=int(fn), tn=int(tn),
                sensitivity=round(sens, 4), specificity=round(spec, 4),
                precision=round(prec, 4), f1=round(f1, 4),
                youden_j=round(sens + spec - 1, 4))


def sweep(uvri: np.ndarray, y: np.ndarray) -> list[dict]:
    grid = np.round(np.unique(np.concatenate([uvri, np.linspace(0.4, 0.85, 10)])), 4)
    rows = []
    for t in sorted(grid):
        m = metrics_at(uvri, y, float(t))
        m["threshold"] = float(t)
        rows.append(m)
    return rows


def bootstrap_ci(uvri: np.ndarray, y: np.ndarray, n: int, seed: int = 0) -> dict:
    """Resample stories with replacement; refit threshold + AUC each time."""
    rng = np.random.default_rng(seed)
    thr_samples, auc_samples = [], []
    idx = np.arange(len(y))
    for _ in range(n):
        b = rng.choice(idx, size=len(idx), replace=True)
        yb, ub = y[b], uvri[b]
        if yb.sum() < 1 or (1 - yb).sum() < 1:   # need both classes present
            continue
        t, a, _ = youden_threshold(ub, yb)
        thr_samples.append(t)
        auc_samples.append(a)
    if not thr_samples:
        return {}
    thr_samples = np.array(thr_samples)
    auc_samples = np.array(auc_samples)
    return {
        "n_effective": len(thr_samples),
        "threshold_ci95": [round(float(np.percentile(thr_samples, 2.5)), 4),
                           round(float(np.percentile(thr_samples, 97.5)), 4)],
        "threshold_median": round(float(np.median(thr_samples)), 4),
        "auc_ci95": [round(float(np.percentile(auc_samples, 2.5)), 4),
                     round(float(np.percentile(auc_samples, 97.5)), 4)],
        "auc_median": round(float(np.median(auc_samples)), 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Find the UVRI readiness threshold.")
    ap.add_argument("dataset")
    ap.add_argument("--cutoff", type=float, default=3.0,
                    help="expert_rating below this = 'not ready' (default 3.0).")
    ap.add_argument("--phase", choices=["pre", "post"], default="pre",
                    help="Which UVRI to threshold (default pre; recommended).")
    ap.add_argument("--bootstrap", type=int, default=2000,
                    help="Bootstrap resamples for the CI (0 to skip).")
    ap.add_argument("--out", type=Path, default=CONFIG_PATH)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    df = load(args.dataset)
    uvri = compute_uvri(df, args.phase).to_numpy()
    y = (df["expert_rating"] < args.cutoff).astype(int).to_numpy()
    n_pos, n_neg = int(y.sum()), int(len(y) - y.sum())
    if n_pos < 2 or n_neg < 2:
        raise SystemExit(f"Need >=2 per class; not_ready={n_pos}, acceptable={n_neg}. "
                         f"Try a different --cutoff.")

    t, roc_auc, _ = youden_threshold(uvri, y)
    at = metrics_at(uvri, y, t)

    print("=" * 66)
    print(f"Dataset      : {Path(args.dataset).name}  (phase={args.phase})")
    print(f"Ground truth : expert_rating < {args.cutoff}  "
          f"-> not_ready={n_pos}, acceptable={n_neg}")
    print(f"AUC          : {roc_auc:.4f}")
    print(f"THRESHOLD    : flag NOT READY when UVRI <= {t:.4f}   (Youden J={at['youden_j']})")
    print(f"  sensitivity={at['sensitivity']}  specificity={at['specificity']}  "
          f"precision={at['precision']}  F1={at['f1']}")
    print(f"  confusion  : TP={at['tp']} FP={at['fp']} FN={at['fn']} TN={at['tn']}")
    print("-" * 66)
    print("Threshold sweep (flag when UVRI <= t):")
    print(f"{'t':>7} {'TP':>3} {'FP':>3} {'FN':>3} {'TN':>3} "
          f"{'Sens':>6} {'Spec':>6} {'Prec':>6} {'F1':>6} {'J':>6}")
    for r in sweep(uvri, y):
        print(f"{r['threshold']:>7.4f} {r['tp']:>3} {r['fp']:>3} {r['fn']:>3} {r['tn']:>3} "
              f"{r['sensitivity']:>6.3f} {r['specificity']:>6.3f} "
              f"{r['precision']:>6.3f} {r['f1']:>6.3f} {r['youden_j']:>6.3f}")

    boot = {}
    if args.bootstrap:
        boot = bootstrap_ci(uvri, y, args.bootstrap)
        if boot:
            print("-" * 66)
            print(f"Bootstrap ({boot['n_effective']} valid resamples):")
            print(f"  threshold 95% CI: {boot['threshold_ci95']}  "
                  f"(median {boot['threshold_median']})")
            print(f"  AUC       95% CI: {boot['auc_ci95']}  (median {boot['auc_median']})")
    print("=" * 66)

    if args.no_write:
        return
    payload = {
        "threshold": round(t, 4),
        "rule": "flag_not_ready_if_uvri_leq_threshold",
        "phase": args.phase,
        "ground_truth_cutoff": args.cutoff,
        "auc": round(roc_auc, 4),
        **at,
        "n_not_ready": n_pos, "n_acceptable": n_neg,
        "bootstrap": boot,
        "weights": WEIGHTS,
        "calibrated_on": Path(args.dataset).name,
        "calibrated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()