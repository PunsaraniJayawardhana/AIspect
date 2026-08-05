"""
backend/scripts/uvri_significance_tests.py

Runs the formal statistical validity tests for the UVRI formula against a
dataset of stories with pre/post-enrichment sub-scores and human expert
ratings (the same shape as Book1.xlsx / your Task A collection).

Tests performed:
  1. Delta-UVRI significance -- paired Wilcoxon signed-rank test comparing
     UVRI_pre vs UVRI_post (using the FINAL AHP-derived weights, not the
     old equal-0.25 placeholder), plus a matched-pairs rank-biserial
     effect size.
  2. Known-groups validity -- Mann-Whitney U test comparing UVRI_pre
     between human-rated-high vs human-rated-low story groups, split at
     the sample median (a fixed threshold like >=4/<=2 can produce a
     badly imbalanced split if ratings cluster tightly, as they did in
     the original 28-story dataset -- median split avoids that).
  3. Ablation study -- recomputes UVRI_pre with each of the four terms
     zeroed out in turn (weight redistributed to the remaining three),
     and reports how much the correlation with expert_rating drops --
     or, notably, whether it INCREASES, which flags a term whose
     AHP-assigned importance may not match its empirical predictive
     contribution in this dataset.
  4. Sensitivity analysis -- perturbs each final weight by +/-0.05
     (renormalised to sum to 1) and confirms the ablation/correlation
     conclusions are stable across that range.

Usage:
    python -m backend.scripts.uvri_significance_tests path/to/ratings.xlsx
"""

import sys
import numpy as np
import pandas as pd
from scipy import stats

# Final AHP-derived weights (see backend/scripts/fit_ahp_weights.py)
WEIGHTS = {
    "coverage": 0.0697,
    "specificity": 0.3154,
    "ambiguity": 0.1685,
    "testability": 0.4464,
}

COL_MAP_PRE = {
    "coverage": "cov_pre", "specificity": "spec_pre",
    "ambiguity": "amb_pre", "testability": "test_pre",
}
COL_MAP_POST = {
    "coverage": "cov_post", "specificity": "spec_post",
    "ambiguity": "amb_post", "testability": "test_post",
}


def load_data(path: str) -> pd.DataFrame:
    """
    Loads the ratings spreadsheet. Strips whitespace from column names
    (a real trailing-space issue was found in one export, e.g. 'amb_post '
    instead of 'amb_post') and drops rows with no story_id (blank trailing
    rows some spreadsheet tools leave behind).
    """
    df = pd.read_excel(path, sheet_name=0)
    df.columns = df.columns.str.strip()
    df = df.dropna(subset=["story_id"]).reset_index(drop=True)

    n_missing_rating = df["expert_rating"].isna().sum()
    if n_missing_rating:
        missing_ids = df.loc[df["expert_rating"].isna(), "story_id"].tolist()
        print(f"NOTE: {n_missing_rating} story(ies) have no expert_rating and will "
              f"be excluded from correlation-based tests (ablation, sensitivity, "
              f"known-groups): {missing_ids}\n")

    return df


def compute_uvri(df: pd.DataFrame, col_map: dict, weights: dict) -> np.ndarray:
    return sum(weights[term] * df[col_map[term]].values for term in weights)


def wilcoxon_delta_test(df: pd.DataFrame):
    uvri_pre = compute_uvri(df, COL_MAP_PRE, WEIGHTS)
    uvri_post = compute_uvri(df, COL_MAP_POST, WEIGHTS)

    print("=" * 70)
    print("1. DELTA-UVRI SIGNIFICANCE (paired Wilcoxon signed-rank test)")
    print("=" * 70)
    print(f"Using final AHP weights: {WEIGHTS}\n")

    mean_pre, mean_post = uvri_pre.mean(), uvri_post.mean()
    delta = uvri_post - uvri_pre
    n_improved = (delta > 0).sum()
    n_same = (delta == 0).sum()
    n_worse = (delta < 0).sum()

    print(f"Mean UVRI_pre:  {mean_pre:.4f}")
    print(f"Mean UVRI_post: {mean_post:.4f}")
    print(f"Mean delta:     {delta.mean():.4f}")
    print(f"Stories improved / unchanged / worse: {n_improved} / {n_same} / {n_worse}\n")

    nonzero_delta = delta[delta != 0]
    if len(nonzero_delta) < 1:
        print("No non-zero differences -- cannot run Wilcoxon test.")
        return uvri_pre, uvri_post

    stat, p_value = stats.wilcoxon(nonzero_delta)
    ranks = stats.rankdata(np.abs(nonzero_delta))
    r_plus = ranks[nonzero_delta > 0].sum()
    r_minus = ranks[nonzero_delta < 0].sum()
    effect_size = (r_plus - r_minus) / (r_plus + r_minus)

    print(f"Wilcoxon W = {stat:.4f},  p = {p_value:.6f}")
    print(f"Matched-pairs rank-biserial effect size r = {effect_size:.4f}")
    sig = "SIGNIFICANT (p<0.05)" if p_value < 0.05 else "NOT significant at p<0.05"
    print(f"-> {sig}\n")

    return uvri_pre, uvri_post


def known_groups_test(df: pd.DataFrame, uvri_pre: np.ndarray):
    print("=" * 70)
    print("2. KNOWN-GROUPS VALIDITY (Mann-Whitney U, median split)")
    print("=" * 70)
    expert = df["expert_rating"].values

    n_missing = np.isnan(expert).sum()
    if n_missing:
        missing_ids = df.loc[df["expert_rating"].isna(), "story_id"].tolist()
        print(f"WARNING: {n_missing} story(ies) have no expert_rating and are "
              f"excluded from this test: {missing_ids}\n")

    valid_mask = ~np.isnan(expert)
    expert_valid = expert[valid_mask]
    uvri_valid = uvri_pre[valid_mask]

    median = np.median(expert_valid)
    print(f"Median expert_rating across {len(expert_valid)} rated stories: {median:.4f}")
    print("Using a median split (a fixed-threshold split can produce a badly "
          "imbalanced group sizes if ratings cluster tightly in the middle "
          "of the scale).\n")

    high_mask = expert_valid > median
    low_mask = expert_valid <= median

    high_scores = uvri_valid[high_mask]
    low_scores = uvri_valid[low_mask]

    print(f"High-rated group (expert_rating > median): n={len(high_scores)}, "
          f"mean UVRI_pre={high_scores.mean():.4f}" if len(high_scores) else "High-rated group: n=0")
    print(f"Low-rated group  (expert_rating <= median): n={len(low_scores)}, "
          f"mean UVRI_pre={low_scores.mean():.4f}" if len(low_scores) else "Low-rated group: n=0")

    if len(high_scores) < 2 or len(low_scores) < 2:
        print("\nToo few stories in one or both groups for a reliable test.\n")
        return

    stat, p_value = stats.mannwhitneyu(high_scores, low_scores, alternative="greater")
    print(f"\nMann-Whitney U = {stat:.4f},  p = {p_value:.6f}  (one-sided: high > low)")
    sig = "SIGNIFICANT (p<0.05)" if p_value < 0.05 else "NOT significant at p<0.05"
    print(f"-> {sig}\n")


def ablation_study(df: pd.DataFrame):
    print("=" * 70)
    print("3. ABLATION STUDY (correlation with expert_rating, term removed)")
    print("=" * 70)
    df_valid = df.dropna(subset=["expert_rating"]).reset_index(drop=True)
    expert = df_valid["expert_rating"].values

    full_uvri = compute_uvri(df_valid, COL_MAP_PRE, WEIGHTS)
    full_r, full_p = stats.pearsonr(full_uvri, expert)
    print(f"FULL MODEL (all four terms): r={full_r:.4f}  p={full_p:.4f}  (n={len(df_valid)})\n")

    for dropped in WEIGHTS:
        remaining = [t for t in WEIGHTS if t != dropped]
        remaining_weight_sum = sum(WEIGHTS[t] for t in remaining)
        ablated_weights = {t: WEIGHTS[t] / remaining_weight_sum for t in remaining}
        ablated_weights[dropped] = 0.0

        ablated_uvri = compute_uvri(df_valid, COL_MAP_PRE, ablated_weights)
        r, p = stats.pearsonr(ablated_uvri, expert)
        delta_r = full_r - r
        flag = ("  <-- removing this term IMPROVES correlation "
                "(worth investigating)" if delta_r < 0 else "")
        print(f"Without {dropped:<14}: r={r:.4f}  p={p:.4f}  "
              f"(drop from full model: {delta_r:+.4f}){flag}")

    print()


def sensitivity_analysis(df: pd.DataFrame):
    print("=" * 70)
    print("4. SENSITIVITY ANALYSIS (perturb each weight +/-0.05, renormalised)")
    print("=" * 70)
    df_valid = df.dropna(subset=["expert_rating"]).reset_index(drop=True)
    expert = df_valid["expert_rating"].values
    full_uvri = compute_uvri(df_valid, COL_MAP_PRE, WEIGHTS)
    full_r, _ = stats.pearsonr(full_uvri, expert)
    print(f"Baseline correlation with final weights: r={full_r:.4f}  (n={len(df_valid)})\n")

    for term in WEIGHTS:
        for delta in (-0.05, 0.05):
            perturbed = dict(WEIGHTS)
            perturbed[term] = max(0.0, perturbed[term] + delta)
            total = sum(perturbed.values())
            perturbed = {t: v / total for t, v in perturbed.items()}

            uvri_perturbed = compute_uvri(df_valid, COL_MAP_PRE, perturbed)
            r, _ = stats.pearsonr(uvri_perturbed, expert)
            print(f"{term:<14} {delta:+.2f} -> r={r:.4f}  (change from baseline: {r - full_r:+.4f})")
    print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m backend.scripts.uvri_significance_tests path/to/ratings.xlsx")
        sys.exit(1)

    path = sys.argv[1]
    df = load_data(path)
    print(f"Loaded {len(df)} stories from {path}\n")

    uvri_pre, uvri_post = wilcoxon_delta_test(df)
    known_groups_test(df, uvri_pre)
    ablation_study(df)
    sensitivity_analysis(df)


if __name__ == "__main__":
    main()