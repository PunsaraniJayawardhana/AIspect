# TPRI Detailed Documentation (Current Implementation)

## 1) What TPRI Is

TPRI (Test Prioritization Risk Index) is the ranking score used by Module 3 to prioritize discrepancy-driven (defect-first) tests before execution.

In this codebase, TPRI is implemented in:

- `backend/pipeline/module3/tpri.py`

TPRI is computed per discrepancy, then discrepancies are sorted by descending score and assigned `priority_rank`.

---

## 2) Where TPRI Fits in the Pipeline

### Runtime flow

1. Module 2 produces discrepancy candidates with confidence metadata.
2. Module 3 adapts discrepancy structure and canonical IDs.
3. Module 3 computes TPRI for eligible discrepancies.
4. Module 3 generates defect-first tests in TPRI order (when `app_url` is provided).
5. Module 3 generates coverage-first tests for all ACs.
6. Results are persisted under `output/results`.
7. Evaluation scripts compare TPRI ordering vs baselines using APFD.

### Main integration points

- Discrepancy normalization and adaptation:
  - `backend/pipeline/module3/input_schema.py`
- TPRI scoring and ranking:
  - `backend/pipeline/module3/tpri.py`
- Test generation that consumes TPRI:
  - `backend/pipeline/module3/test_generator.py`
- Orchestration entry that invokes Module 3:
  - `backend/pipeline/orchestrator.py`

---

## 3) Mathematical Definition

The implementation computes a weighted normalized sum over four components:

$$
\mathrm{TPRI} = \frac{\alpha \cdot CI + \beta \cdot ST + \gamma \cdot RC + \delta \cdot FS}{\alpha + \beta + \gamma + \delta}
$$

Default weights:

- $\alpha = 0.25$ (CI)
- $\beta = 0.25$ (ST)
- $\gamma = 0.25$ (RC)
- $\delta = 0.25$ (FS)

Implementation details:

- If all weights sum to 0, code falls back to equal weights and denominator 1.0.
- Output values are rounded to 4 decimals in the TPRI payload.

Source: `compute_tpri` in `backend/pipeline/module3/tpri.py`.

---

## 4) Component Definitions and Exact Code Behavior

## 4.1 CI (Confidence Index)

- Input field: `confidence_index` from Module 2 discrepancy objects.
- Typical range: 0.0 to 1.0.
- Used as `float(ci)` in formula.

### Eligibility gate before TPRI scoring

`prioritize_discrepancies` applies this filter:

- Keep discrepancy if either:
  - `confidence_label == "HIGH"`, or
  - `confidence_index >= CI_HIGH_THRESHOLD`

So a non-HIGH label can still pass if numeric CI is above threshold.

Threshold source:

- `CI_HIGH_THRESHOLD` in `backend/config/settings.py`
- Current default from env fallback: `0.80`

## 4.2 ST (Severity Type)

Mapped in `SEVERITY_LOOKUP` (exact keys currently used):

- `Missing Element`: 1.0
- `Business Rule Violation`: 0.9
- `Interaction Flow Error`: 0.7
- `Wrong Label`: 0.6
- `Layout Constraint Mismatch`: 0.4

Unknown discrepancy types default to `0.5`.

Important normalization note:

- `input_schema.normalize_discrepancy_type` converts underscores to spaces.
- Example: `Missing_Element` becomes `Missing Element`.

## 4.3 RC (Requirement Criticality)

`get_rc_score(ac_text, user_story)` calls the configured LLM through `call_llm` and asks for strict JSON:

```json
{"rc_score": 0.0, "reasoning": "one sentence explanation referencing the AC"}
```

Behavior details:

- RC score is clamped into [0.0, 1.0].
- Markdown code fences in model output are stripped before JSON parsing.
- On parse/provider failure, fallback is:
  - `rc_score = 0.5`
  - reasoning = `LLM provider unavailable; using neutral RC fallback.`

## 4.4 FS (Failure Spread)

`compute_fs(ac_text, all_acs)` estimates how broadly the AC overlaps with others using token-level Jaccard similarity.

Algorithm:

1. Tokenize text with regex `[a-z0-9]+` and lowercase.
2. For each other AC:
   - Compute Jaccard = intersection/union.
   - If Jaccard > 0.20, count as related.
3. Return:

$$
FS = \frac{\text{related count}}{\max(1, (|ACs| - 1))}
$$

Edge case:

- If AC count <= 1, FS returns 0.0.

---

## 5) Ranking Semantics and Tie-Breakers

After computing component fields, discrepancies are sorted by:

1. `tpri_score` descending
2. `confidence_index` descending (tie-break)

Then `priority_rank` is assigned starting from 1.

Returned record includes original discrepancy fields +:

- `ci`, `st`, `rc`, `fs`
- `rc_reasoning`
- `tpri_score`
- `priority_rank`

Source: `prioritize_discrepancies` in `backend/pipeline/module3/tpri.py`.

---

## 6) Data Contract Expected by TPRI Layer

Minimal discrepancy fields used directly or via fallback:

- `confidence_index`
- `confidence_label`
- `discrepancy_type`
- `ac_text` or `requirement_id`
- Optional metadata carried through unchanged (`description`, `location`, etc.)

Upstream adaptation in `backend/pipeline/module3/input_schema.py` ensures:

- Canonical `requirement_id`
- Normalized `ac_text`
- Canonical discrepancy type formatting
- Stable `discrepancy_id` generation when missing

AC list input used for FS:

- `enriched_acs` from normalized explicit + implicit ACs.

---

## 7) How TPRI Drives Test Generation

### In `run_test_generator`

1. Normalize ACs.
2. Adapt discrepancies.
3. Compute prioritized discrepancy list via TPRI.
4. If `app_url` exists:
   - Generate defect-first tests from prioritized list.
5. Always generate coverage-first AC tests.

Return value:

- `defect_tests + coverage_tests` (defect-first records appear first when enabled).

### Defect-first test record fields populated from TPRI

- `tpri_score`
- `priority_rank`
- `ci`, `st`, `rc`, `rc_reasoning`, `fs`

Priority label for output test case:

- `High` if score >= 0.75
- `Medium` if score >= 0.50
- else `Low`

Source: `backend/pipeline/module3/test_generator.py`.

---

## 8) APFD Evaluation Related to TPRI

APFD evaluation in this repository is read-only over existing test results (no Cypress reruns).

Core file:

- `backend/pipeline/module3/evaluate_tpri.py`

APFD formula used:

$$
APFD = 1 - \frac{\sum TF_i}{n \cdot m} + \frac{1}{2n}
$$

where:

- $n$ = number of tests in ordering
- $m$ = number of detected faults
- $TF_i$ = 1-based position of each fault in the ordering

Important current behavior:

- If no tests (`n <= 0`), APFD returns `None`.
- If no fault positions, APFD returns `None`.
- TTFF (time-to-first-fault proxy) returns `n + 1` when no fault exists.

Orderings compared:

- TPRI ordering
- AC declaration ordering
- Deterministic random baseline (`random_runs`, seed-based)

---

## 9) Reporting Layer and Output Artifacts

Report generator:

- `backend/pipeline/module3/generate_eval_report.py`

Outputs:

- `output/eval/results_table.md`
- `output/eval/results_table.csv`
- `output/eval/weight_grid.csv`
- `output/eval/charts/apfd_comparison.png`
- `output/eval/charts/ablation_apfd_drop.png`

Current exclusion logic in results table:

- Excludes ticket IDs listed in `EXCLUDED_TICKET_REASONS` (currently includes EXC-10).
- Excludes tickets with zero confirmed faults (`APFD undefined`).

Current observed APFD table (`output/eval/results_table.md`):

- EXC-1: TPRI 0.9667, AC-order 0.9556, Random 0.4593
- EXC-14: TPRI 0.9790, AC-order 0.9786, Random 0.5252
- EXC-15: TPRI 0.9787, AC-order 0.9787, Random 0.4626
- EXC-2: TPRI 0.9592, AC-order 0.9541, Random 0.4561
- EXC-5: TPRI 0.9592, AC-order 0.9574, Random 0.4815
- Average: TPRI 0.9686, AC-order 0.9649, Random 0.4769

---

## 10) Weight Tuning for TPRI

Tuning module:

- `backend/pipeline/module3/tune_weights.py`

Purpose:

- Grid-search weight vectors for `ci, st, rc, fs` over simplex steps (default 0.1).
- Score each weight vector by mean APFD across evaluation tickets.

Candidate generation:

- Enumerates all non-negative weights summing to 1.0 (discretized by `step`).

Evaluation process per candidate:

1. Re-score stored tests using weighted sum over stored component values.
2. Re-order tests by score.
3. Compute APFD from provided fault IDs.
4. Average APFD across tickets with defined APFD.

Current artifact:

- `output/eval/weight_grid.csv`

Notes from current grid sample:

- Multiple top-ranked candidates are tied (same mean APFD).
- Many top candidates heavily weight ST/FS and set RC to 0 in this dataset.
- This indicates dataset-specific separability and potential overfitting risk if used as universal weights.

---

## 11) Known Behavioral Nuances and Caveats

1. RC is LLM-dependent and can vary by provider/model/runtime failures.
2. ST mapping depends on exact normalized discrepancy type strings.
3. FS is lexical overlap, not semantic embedding similarity.
4. Eligibility gate uses both label and numeric threshold; label and numeric value can disagree.
5. APFD semantics differ slightly across modules:
   - `evaluate_tpri.py` returns `None` for undefined APFD.
   - helper functions in other modules may return `1.0` in no-fault scenarios for plotting/tuning convenience.
6. Tuning results depend strongly on fault label quality and ticket mix.

---

## 12) Reproducible Commands

Run read-only evaluation summary for tickets/files:

```bash
python -m backend.pipeline.module3.evaluate_tpri EXC-1 EXC-2 --pretty
```

Generate report artifacts:

```bash
python -m backend.pipeline.module3.generate_eval_report --tickets EXC-10 EXC-1 EXC-14 EXC-15 EXC-2 EXC-5 EXC-54
```

Tune TPRI weights from config:

```bash
python -m backend.pipeline.module3.tune_weights output/module3/tpri_weight_tuning_config.json --step 0.1 --pretty
```

Standalone TPRI pipeline smoke script (fixture-style local check):

```bash
python -m backend.scripts.test_tpri_pipeline EXC-2
```

---

## 13) Practical Interpretation Guide

When analyzing one discrepancy:

1. Check CI and confidence label first (eligibility gate).
2. Verify discrepancy type normalization to ensure intended ST mapping.
3. Inspect RC reasoning text for business relevance rationale.
4. Validate FS behavior by comparing AC lexical overlap assumptions.
5. Use final TPRI score for execution priority, not as a defect truth label.

When analyzing portfolio-level performance:

1. Compare TPRI APFD against AC-order and random baselines.
2. Track ticket exclusions (zero-fault, unsupported scenarios) explicitly.
3. Evaluate tuning ties and margins before claiming one best weight vector.

---

## 14) Source Index

- `backend/pipeline/module3/tpri.py`
- `backend/pipeline/module3/input_schema.py`
- `backend/pipeline/module3/test_generator.py`
- `backend/pipeline/module3/evaluate_tpri.py`
- `backend/pipeline/module3/generate_eval_report.py`
- `backend/pipeline/module3/tune_weights.py`
- `backend/tests/test_module3_eval_report_apfd_only.py`
- `backend/config/settings.py`
- `output/eval/results_table.md`
- `output/eval/results_table.csv`
- `output/eval/weight_grid.csv`
