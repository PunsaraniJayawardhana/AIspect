# AIspect — Module 3 Specification

## 1. Overview

Module 3 is the test generation, prioritization, and automated bug reporting stage of the AIspect pipeline. It receives output from Module 1 (enriched acceptance criteria) and Module 2 (confidence-annotated discrepancy JSON) and produces TPRI-ranked test documentation, executable Cypress scripts, and Jira bug tickets.

The research novelty of Module 3 is the **Test Prioritization Risk Index (TPRI)** — a computable, multi-signal formula that assigns each generated test case a priority score before execution, so that the most critical defects are verified against the live application first.

Module 3 is implemented entirely within:

```
backend/pipeline/module3/
backend/scripts/fixtures/
```

It does **not** modify any file outside these directories. It reads from Module 1 and Module 2 outputs through the existing orchestrator interface without altering those modules.

---

## 2. Goals

1. Compute a TPRI score for every HIGH-confidence discrepancy received from Module 2.
2. Generate Mode 1 coverage-first test cases from all enriched ACs received from Module 1.
3. Generate Mode 2 defect-first Cypress scripts from TPRI-ranked HIGH-confidence discrepancies.
4. Execute Mode 2 Cypress scripts against the deployed application in TPRI order.
5. Automatically create Jira bug tickets for every confirmed live defect.
6. Export all test cases as a TPRI-ranked DOCX document and Markdown file.
7. Compute APFD scores for TPRI ordering vs random vs severity-only for research evaluation.
8. Support fixture-based development so the module runs fully while Module 1 and Module 2 are still stubbed.

---

## 3. Repository Structure — Module 3 Files Only

All new files created by Module 3 are listed below. No existing file outside `backend/pipeline/module3/` is modified except `backend/pipeline/orchestrator.py` (two function calls updated).

```
backend/
├── pipeline/
│   └── module3/
│       ├── __init__.py                  (exists — empty, unchanged)
│       ├── test_generator.py            (exists as stub — REPLACE)
│       ├── cypress_runner.py            (exists as stub — REPLACE)
│       ├── tpri.py                      (NEW — TPRI engine)
│       ├── fixture_loader.py            (NEW — dev fixture support)
│       ├── docx_exporter.py             (NEW — DOCX/MD export)
│       └── apfd_evaluator.py            (NEW — research evaluation)
├── scripts/
│   └── fixtures/
│       ├── EXC-1_module1.json           (NEW — Module 1 fixture)
│       ├── EXC-1_module2.json           (NEW — Module 2 fixture)
│       ├── EXC-2_module1.json           (NEW — second user story)
│       ├── EXC-2_module2.json           (NEW — second user story)
│       ├── EXC-3_module1.json           (NEW — third user story)
│       └── EXC-3_module2.json           (NEW — third user story)
└── scripts/
    └── test_module3_standalone.py       (NEW — standalone test runner)
```

**Files touched in other modules: none.**

**One orchestrator edit** — two lines in `backend/pipeline/orchestrator.py` that currently call the stubbed `test_generator` and `cypress_runner` are updated to call the real implementations. No logic in the orchestrator changes.

---

## 4. Technology Stack — Module 3 Additions

All dependencies already exist in the project `requirements.txt` or are standard library. No new packages are required.

| Dependency | Already in project | Purpose in Module 3 |
|---|---|---|
| `anthropic>=0.40.0` | Yes | RC scoring via Claude API, test case generation, Cypress script generation |
| `python-docx>=1.1.0` | Yes | DOCX test case export |
| `subprocess` | stdlib | Cypress execution |
| `json` | stdlib | Fixture loading, API response parsing |
| `os`, `tempfile` | stdlib | File handling for Cypress scripts |
| `random` | stdlib | Random ordering baseline for APFD |
| `logging` | stdlib | Fixture loader diagnostics |

---

## 5. Data Contracts

### 5.1 Inputs from Module 1 (via orchestrator)

Module 3 reads the following fields from the orchestrator job context. These match the existing job result payload defined in the system spec.

```python
explicit_acs: list[dict]
# Each dict:
# {
#   "ac_id": "AC-01",
#   "text": "The login page shall display an email input field",
#   "type": "explicit"
# }

implicit_acs: list[dict]
# Each dict:
# {
#   "ac_id": "AC-06",
#   "text": "The login page shall display a password show/hide toggle",
#   "type": "implicit",
#   "inference_rationale": "Standard on all login screens"
# }

story_text: str
# "As a registered user, I want to log in..."

nav_path: str
# "Home > Login"

story_key: str
# "EXC-1"
```

### 5.2 Inputs from Module 2 (via orchestrator)

```python
verified_discrepancies: list[dict]
# Each dict:
# {
#   "discrepancy_id": "DISC-01",
#   "requirement_id": "AC-06",
#   "ac_text": "The login page shall display a password show/hide toggle",
#   "discrepancy_type": "Missing_Element",
#   "description": "The password show/hide toggle is absent...",
#   "location": "Login Page — Password Field",
#   "confidence_index": 0.92,
#   "confidence_label": "HIGH",
#   "identified_in_runs": 5
# }
```

**Confidence label filter:** Only discrepancies with `confidence_label == "HIGH"` (CI ≥ 0.80) enter TPRI computation and Mode 2 generation. MEDIUM and LOW discrepancies are ignored.

### 5.3 Optional input

```python
app_url: str | None
# "https://staging.yourapp.com"
# If None, Mode 2 Cypress execution is skipped.
# Mode 1 test generation still runs.
```

### 5.4 Outputs to orchestrator

Module 3 returns three values that the orchestrator stores in `job.result`:

```python
tests: list[dict]
# Combined Mode 1 + Mode 2 test cases.
# Mode 2 entries appear first, sorted by priority_rank ascending.
# Each dict described in Section 7.

cypress_results: list[dict]
# Mode 2 tests with pass/fail results appended.
# Empty list if app_url was None.

bugs_created: list[dict]
# Jira ticket keys for confirmed defects.
# [{"ticket_key": "PROJ-123", "discrepancy_id": "DISC-01"}, ...]
```

---

## 6. TPRI Formula and Components

### 6.1 Formula

```
TPRI = α(CI) + β(ST) + γ(RC) + δ(FS)
```

All weights initialised to 0.25 (equal weighting) as the research baseline. Optimal weights are determined empirically through the ablation study described in Section 11.

### 6.2 Component definitions

**CI — Confidence Index**
Source: Module 2 output field `confidence_index`.
Range: 0.0–1.0.
Meaning: How certain is the AI that this discrepancy is real (not a hallucination). Computed by Module 2's multi-pass validation across N runs.

**ST — Severity Type**
Source: Fixed taxonomy lookup keyed on `discrepancy_type`.
Range: 0.4–1.0.
Meaning: How severely does this discrepancy type impact user functionality.

Literature basis: IEEE Standard 1044-2009 (Software Anomaly Classification) and Chillarege et al. 1992 (Orthogonal Defect Classification).

| Discrepancy Type | ST Score | IEEE 1044 Category | ODC Type | Justification |
|---|---|---|---|---|
| `Missing_Element` | 1.0 | Blocking | Function | Element absent — functionality completely blocked |
| `Business_Rule_Violation` | 0.9 | Major | Algorithm | Core logic incorrect — wrong outcomes produced |
| `Interaction_Flow_Error` | 0.7 | Major | Interface | Navigation broken — user cannot complete task |
| `Wrong_Label` | 0.6 | Minor | Assignment | Misleading but core workflow functional |
| `Layout_Constraint_Mismatch` | 0.4 | Cosmetic | Build | Visual only — no functional impact |

**RC — Requirement Criticality**
Source: Claude Sonnet API call on the violated AC text.
Range: 0.0–1.0.
Meaning: How central is this acceptance criterion to the core business value of the user story.

The RC prompt asks Claude to score on three dimensions: centrality to business value, dependency (would the story fail without this), and protection of user data or core workflow. Claude returns a structured JSON response containing the score and a one-sentence reasoning string.

Literature basis: Equivalent to Customer Priority (CP) in PORT 2.0 (Srikanth et al., 2015), but computed automatically by LLM from AC text rather than assigned manually by product teams. This removes the subjectivity limitation acknowledged by PORT 2.0.

**FS — Failure Spread**
Source: Computed from word-overlap ratio between the violated AC and all other ACs in the enriched set.
Range: 0.0–1.0.
Meaning: How many other ACs share semantic overlap with this one. A test that touches a widely-referenced AC validates more of the requirement surface in a single execution.

Computation: For each other AC, calculate the Jaccard similarity of word sets. If similarity > 0.20, the AC is considered related. FS = (related AC count) / (total ACs - 1).

Literature basis: Analogous to the additional coverage principle in Elbaum et al. (2002), which showed greedy breadth-first selection outperforms total-coverage ordering.

---

## 7. Test Case Data Model

Every test case produced by Module 3 — whether Mode 1 or Mode 2 — conforms to this structure:

```python
{
    # Identity
    "tc_id":           str,   # "TC-M1-001" or "TC-M2-001"
    "mode":            str,   # "coverage_first" | "defect_first"
    "ticket_id":       str,   # originating Jira story key
    "ac_id":           str,   # AC this test covers (Mode 1)
    "discrepancy_id":  str,   # discrepancy this tests (Mode 2)
    "requirement_id":  str,   # AC violated by discrepancy (Mode 2)

    # Content
    "scenario":        str,   # short test description
    "priority":        str,   # "High" | "Medium" | "Low"
    "steps":           list[str],
    "expected_result": str,

    # TPRI fields (Mode 2 only; None for Mode 1)
    "tpri_score":      float | None,
    "priority_rank":   int | None,
    "ci":              float | None,
    "st":              float | None,
    "rc":              float | None,
    "rc_reasoning":    str | None,
    "fs":              float | None,

    # Cypress fields (Mode 2 only)
    "cypress_script":  str | None,

    # Execution results (populated after Cypress runs)
    "passed":          bool | None,
    "confirmed_fault": bool | None,

    # Jira output
    "jira_ticket":     str | None,   # "PROJ-123" if bug created
}
```

---

## 8. File Specifications

### 8.1 backend/pipeline/module3/tpri.py (NEW)

**Purpose:** Computes TPRI scores for HIGH-confidence discrepancies and returns them sorted by priority.

**Public functions:**

```python
def get_rc_score(ac_text: str, user_story: str) -> dict:
    """
    Calls Claude Sonnet API with structured RC scoring prompt.
    Returns {"rc_score": float, "reasoning": str}.
    Uses settings.claude_model and settings.anthropic_api_key.
    """

def compute_fs(ac_text: str, all_acs: list[str]) -> float:
    """
    Computes Jaccard word-overlap ratio between ac_text
    and every other AC in all_acs.
    Returns proportion of ACs with overlap > 0.20.
    """

def compute_tpri(
    ci: float,
    discrepancy_type: str,
    ac_text: str,
    user_story: str,
    all_acs: list[str],
    weights: dict | None = None
) -> dict:
    """
    Computes TPRI = α(CI) + β(ST) + γ(RC) + δ(FS).
    Returns full component breakdown for reporting.
    Default weights: alpha=beta=gamma=delta=0.25.
    """

def prioritize_discrepancies(
    discrepancies: list[dict],
    enriched_acs: list[dict],
    user_story: str,
    weights: dict | None = None
) -> list[dict]:
    """
    Filters to HIGH-confidence only.
    Computes TPRI for each.
    Returns sorted descending by tpri_score with priority_rank assigned.
    """
```

**RC prompt template:**

```
You are a senior QA analyst evaluating the business criticality
of an acceptance criterion for a software feature.

User Story: {user_story}
Acceptance Criterion: {ac_text}

Score this acceptance criterion on a scale of 0.0 to 1.0 based on:
1. CENTRALITY: How central is this to the core business value?
2. DEPENDENCY: Would the user story fail entirely without this?
3. PROTECTION: Does this protect user data or core workflow?

Respond ONLY in this exact JSON format with no other text:
{
  "rc_score": 0.0,
  "reasoning": "one sentence explanation referencing the AC"
}
```

**Dependencies:** `anthropic`, `backend.config.settings`

---

### 8.2 backend/pipeline/module3/test_generator.py (REPLACE STUB)

**Purpose:** Generates Mode 1 coverage-first test cases and Mode 2 defect-first Cypress scripts. Main entry point called by the orchestrator.

**Public functions:**

```python
def generate_coverage_tests(
    enriched_acs: list[dict],
    user_story: str,
    ticket_id: str
) -> list[dict]:
    """
    Mode 1. Calls Claude API once per AC.
    Requests positive, negative, and boundary test cases.
    Returns list of test case dicts with tc_id "TC-M1-NNN".
    tpri_score and priority_rank are None for all Mode 1 tests.
    """

def generate_defect_tests(
    prioritized_discrepancies: list[dict],
    app_url: str,
    ticket_id: str
) -> list[dict]:
    """
    Mode 2. Calls Claude API once per HIGH-confidence discrepancy.
    Generates Cypress script that navigates to app_url and asserts
    whether the discrepancy exists in the live application.
    Returns list of test case dicts with tc_id "TC-M2-NNN".
    Tests are already in TPRI order (input is pre-sorted).
    """

def run_test_generator(
    verified_discrepancies: list[dict],
    explicit_acs: list[dict],
    implicit_acs: list[dict],
    story_text: str,
    story_key: str,
    app_url: str | None = None,
    nav_path: str = ""
) -> list[dict]:
    """
    Main orchestrator entry point.
    1. Resolves fixture fallback via fixture_loader.
    2. Calls prioritize_discrepancies for TPRI computation.
    3. Calls generate_coverage_tests for Mode 1.
    4. Calls generate_defect_tests for Mode 2 (if app_url provided).
    5. Returns Mode 2 tests + Mode 1 tests (Mode 2 first).
    """
```

**Mode 1 Claude prompt structure:**

```
You are a QA engineer writing test cases.

User Story: {user_story}
Acceptance Criterion ({ac_id}): {ac_text}

Generate test cases covering:
1. One POSITIVE test (valid, happy-path scenario)
2. One NEGATIVE test (invalid input or missing element)
3. One BOUNDARY test where applicable

Respond ONLY as a JSON array, no markdown fences:
[
  {
    "scenario": "short description of what is tested",
    "type": "positive | negative | boundary",
    "priority": "High | Medium | Low",
    "steps": ["step 1", "step 2", "step 3"],
    "expected_result": "what should happen"
  }
]
```

**Mode 2 Claude prompt structure:**

```
You are a Cypress test automation engineer.

Application URL: {app_url}
Discrepancy Type: {discrepancy_type}
Description: {description}
UI Location: {location}
Violated AC: {ac_text}
TPRI Score: {tpri_score} | Rank: {priority_rank}

Write a complete Cypress test that navigates to the page and asserts
whether the described discrepancy exists in the live application.
Selector preference: data-testid > aria-label > visible text.

Respond with raw JavaScript only. No markdown. Start with: describe(
```

**Dependencies:** `anthropic`, `backend.config.settings`, `backend.pipeline.module3.tpri`, `backend.pipeline.module3.fixture_loader`

---

### 8.3 backend/pipeline/module3/cypress_runner.py (REPLACE STUB)

**Purpose:** Executes Mode 2 Cypress scripts in TPRI rank order against the live application. Appends pass/fail results to each test dict.

**Public functions:**

```python
def run_cypress_tests(tests: list[dict]) -> list[dict]:
    """
    Filters to Mode 2 tests only.
    Writes each cypress_script to a temp file.
    Runs: npx cypress run --spec {path} --headless
    Appends "passed" (bool) and "confirmed_fault" (bool) to each dict.
    Returns updated test list.
    Requires: npm install cypress in project root.
    If Cypress is not installed, logs warning and returns tests unchanged.
    """

def get_confirmed_faults(cypress_results: list[dict]) -> list[dict]:
    """
    Returns only tests where confirmed_fault is True.
    Used by orchestrator to determine which tests trigger bug tickets.
    """
```

**Execution behaviour:**
- Cypress runs one script at a time in TPRI rank order.
- `returncode == 0` → passed = True, confirmed_fault = False.
- `returncode != 0` → passed = False, confirmed_fault = True.
- Subprocess timeout: 60 seconds per script.
- If `npx` is not found, function logs a warning and returns tests with `passed=None`, `confirmed_fault=None`.

**Dependencies:** `subprocess`, `os`, `tempfile`, `logging`

---

### 8.4 backend/pipeline/module3/fixture_loader.py (NEW)

**Purpose:** Provides realistic fixture data when Module 1 and Module 2 are still stubbed. Auto-detects stubs without requiring manual configuration. Bypassed automatically when real data is present.

**Public functions:**

```python
def get_module1_inputs(
    story_key: str,
    explicit_acs: list,
    implicit_acs: list,
    story_text: str,
    nav_path: str
) -> tuple[list, list, str, str]:
    """
    Returns (explicit_acs, implicit_acs, story_text, nav_path).
    If USE_MODULE_FIXTURES=true and stub detected:
      loads backend/scripts/fixtures/{story_key}_module1.json.
    If fixture file not found: returns inputs unchanged.
    If USE_MODULE_FIXTURES=false: returns inputs unchanged.
    """

def get_module2_inputs(
    story_key: str,
    verified_discrepancies: list
) -> list:
    """
    Returns verified_discrepancies.
    If USE_MODULE_FIXTURES=true and empty list detected:
      loads backend/scripts/fixtures/{story_key}_module2.json.
    If fixture file not found: returns empty list.
    If USE_MODULE_FIXTURES=false: returns inputs unchanged.
    """
```

**Stub detection logic:**

```python
def _is_stub_acs(acs: list) -> bool:
    # True if empty list.
    # True if first AC contains hardcoded stub text
    # ("email address field", "password field", "confirm password").

def _is_stub_discrepancies(discrepancies: list) -> bool:
    # True if empty list.
```

**Environment variable:**

```bash
USE_MODULE_FIXTURES=true    # default — fixtures active
USE_MODULE_FIXTURES=false   # disable — live data only
```

**Fixture file locations:**

```
backend/scripts/fixtures/{story_key}_module1.json
backend/scripts/fixtures/{story_key}_module2.json
```

**When to disable:** Set `USE_MODULE_FIXTURES=false` in `.env` after both Module 1 and Module 2 complete real implementations. Stub detection also automatically bypasses fixtures when real data is present regardless of the flag.

**Dependencies:** `json`, `os`, `logging`

---

### 8.5 backend/pipeline/module3/docx_exporter.py (NEW)

**Purpose:** Exports all test cases as a structured DOCX file for formal QA reporting and as a Markdown file for version control.

**Public functions:**

```python
def export_to_docx(
    tests: list[dict],
    story_key: str,
    output_path: str
) -> str:
    """
    Creates DOCX with:
    - Title heading: "Test Cases — {story_key}"
    - Table with columns:
        TC ID | Mode | Scenario | Priority | TPRI | Rank | Steps | Expected Result
    - Mode 2 rows appear first (TPRI ordered).
    - Mode 1 rows follow.
    - Returns output_path on success.
    Uses python-docx library.
    """

def export_to_markdown(
    tests: list[dict],
    story_key: str,
    output_path: str
) -> str:
    """
    Creates Markdown table with same columns as DOCX.
    Suitable for version control and CI/CD integration.
    Returns output_path on success.
    """
```

**Output paths (default):**

```
backend/scripts/fixtures/{story_key}_test_cases.docx
backend/scripts/fixtures/{story_key}_test_cases.md
```

**Dependencies:** `python-docx`, `os`

---

### 8.6 backend/pipeline/module3/apfd_evaluator.py (NEW)

**Purpose:** Computes APFD for research evaluation. Used by the standalone test script and ablation study. Not called by the orchestrator in normal pipeline runs.

**Public functions:**

```python
def compute_apfd(
    test_order: list[str],
    fault_detected_by: dict[str, str]
) -> float:
    """
    APFD = 1 - (TF1 + TF2 + ... + TFm) / (n*m) + 1/(2n)

    test_order: list of tc_ids in execution order
    fault_detected_by: {discrepancy_id: tc_id_that_first_detects_it}
    Returns float 0.0–1.0.
    """

def build_fault_map(mode2_tests: list[dict]) -> dict[str, str]:
    """
    Builds fault_detected_by from Cypress results.
    Only includes tests where confirmed_fault is True.
    Returns {discrepancy_id: tc_id}.
    """

def random_apfd(
    mode2_tests: list[dict],
    fault_map: dict,
    runs: int = 5
) -> float:
    """
    Averages APFD over {runs} random shuffles of mode2_tests.
    Provides the random ordering baseline.
    """

def severity_only_apfd(
    mode2_tests: list[dict],
    fault_map: dict
) -> float:
    """
    Sorts mode2_tests by ST score descending only.
    Computes APFD for that ordering.
    Provides the single-signal baseline.
    """

def run_ablation_study(
    discrepancies: list[dict],
    enriched_acs: list[dict],
    user_story: str,
    mode2_tests: list[dict],
    fault_map: dict
) -> dict:
    """
    Runs TPRI five times — once with all factors, then removing
    each factor in turn (weight set to 0.0, others redistributed).
    Returns dict keyed by config name:
    {
        "Full TPRI":   {"apfd": float, "drop": 0.0},
        "Without CI":  {"apfd": float, "drop": float},
        "Without ST":  {"apfd": float, "drop": float},
        "Without RC":  {"apfd": float, "drop": float},
        "Without FS":  {"apfd": float, "drop": float},
    }
    """
```

**APFD formula reference:** Elbaum, Malishevsky & Rothermel, IEEE Transactions on Software Engineering, Vol. 28 No. 2, 2002.

**Dependencies:** `random`, `backend.pipeline.module3.tpri`

---

### 8.7 backend/scripts/test_module3_standalone.py (NEW)

**Purpose:** Runs the full Module 3 pipeline from the command line without starting the FastAPI server. Used for development, debugging, and research evaluation.

**Usage:**

```bash
# Mode 1 only (no Cypress)
python -m backend.scripts.test_module3_standalone EXC-1

# Mode 1 + Mode 2 with Cypress execution
python -m backend.scripts.test_module3_standalone EXC-1 https://staging.yourapp.com

# Run ablation study after Cypress results exist
python -m backend.scripts.test_module3_standalone EXC-1 --ablation
```

**Output:**

```
==================================================
Running Module 3 standalone for: EXC-1
App URL: None (Mode 2 skipped)
==================================================

Generated 14 test cases total
  Mode 2 (defect-first): 3
  Mode 1 (coverage-first): 11

TPRI Rankings (Mode 2):
Rank   TC ID        TPRI     CI     ST     RC     FS     Scenario
--------------------------------------------------------------------------------
1      TC-M2-001    0.7700   0.88   1.0    0.88   0.33   Verify: Forgot Password link...
2      TC-M2-002    0.7000   0.92   1.0    0.72   0.17   Verify: Password toggle...
3      TC-M2-003    0.5650   0.84   0.6    0.65   0.17   Verify: Login button label...

Full JSON saved: backend/scripts/fixtures/EXC-1_module3_output.json
DOCX saved: backend/scripts/fixtures/EXC-1_test_cases.docx
Markdown saved: backend/scripts/fixtures/EXC-1_test_cases.md
```

---

## 9. Fixture Files

Three user stories are provided as fixtures. Each covers a different screen type to support APFD evaluation across varied contexts.

### 9.1 Fixture schema — Module 1

```json
{
  "story_key": "EXC-1",
  "story_text": "As a registered user...",
  "nav_path": "Home > Login",
  "screen_type": "login",
  "explicit_ACs": [
    {"ac_id": "AC-01", "text": "...", "type": "explicit"}
  ],
  "implicit_ACs": [
    {"ac_id": "AC-06", "text": "...", "type": "implicit", "inference_rationale": "..."}
  ],
  "uvri_score": 0.78
}
```

### 9.2 Fixture schema — Module 2

```json
{
  "story_key": "EXC-1",
  "validation_runs": 5,
  "verified_discrepancies": [
    {
      "discrepancy_id": "DISC-01",
      "requirement_id": "AC-06",
      "ac_text": "...",
      "discrepancy_type": "Missing_Element",
      "description": "...",
      "location": "...",
      "confidence_index": 0.92,
      "confidence_label": "HIGH",
      "identified_in_runs": 5
    }
  ]
}
```

### 9.3 Three fixture stories

| Story Key | Screen Type | Explicit ACs | Implicit ACs | HIGH Discrepancies |
|---|---|---|---|---|
| EXC-1 | Login | 5 | 2 | 3 |
| EXC-2 | Sign Up / Registration | 5 | 2 | 3 |
| EXC-3 | Dashboard / Settings form | 4 | 3 | 2 |

---

## 10. Orchestrator Integration

Only two changes are made to `backend/pipeline/orchestrator.py`. No other orchestrator logic is touched.

### 10.1 Replace the Module 3 stub call

Find the existing stub call (currently returns empty list):

```python
# BEFORE — existing stub
from backend.pipeline.module3.test_generator import test_generator
from backend.pipeline.module3.cypress_runner import cypress_runner

tests = test_generator(...)
cypress_results = cypress_runner(...)
```

Replace with:

```python
# AFTER — real implementation
from backend.pipeline.module3.test_generator import run_test_generator
from backend.pipeline.module3.cypress_runner import (
    run_cypress_tests, get_confirmed_faults
)

tests = run_test_generator(
    verified_discrepancies=verified_discrepancies,
    explicit_acs=explicit_acs,
    implicit_acs=implicit_acs,
    story_text=story_text,
    story_key=story_key,
    app_url=app_url,
    nav_path=nav_path
)

cypress_results = []
bugs_created = []

if app_url:
    cypress_results = run_cypress_tests(tests)
    confirmed = get_confirmed_faults(cypress_results)
    for fault in confirmed:
        ticket = await jira_client.create_bug_ticket(
            discrepancy=fault,
            originating_story=story_key
        )
        bugs_created.append({
            "ticket_key":     ticket.get("key"),
            "discrepancy_id": fault.get("discrepancy_id")
        })
```

### 10.2 Add DOCX export after test generation

```python
from backend.pipeline.module3.docx_exporter import (
    export_to_docx, export_to_markdown
)

export_to_docx(tests, story_key,
    f"backend/scripts/fixtures/{story_key}_test_cases.docx")
export_to_markdown(tests, story_key,
    f"backend/scripts/fixtures/{story_key}_test_cases.md")
```

### 10.3 Emit progress events

The orchestrator already emits events. Add these two around Module 3:

```python
await job.emit("module3_started")
# ... run_test_generator, run_cypress_tests, create_bug_tickets
await job.emit("module3_done")
```

---

## 11. Research Evaluation — APFD and Ablation Study

This section describes the evaluation procedure for the TPRI research contribution. It is run separately from the main pipeline using `apfd_evaluator.py` and the standalone script.

### 11.1 Evaluation procedure

After running the full pipeline on 3–5 user stories with a real deployed application:

1. Collect pass/fail Cypress results for all Mode 2 tests.
2. Build the fault map: `{discrepancy_id: tc_id_that_confirmed_it}`.
3. Compute APFD for three orderings per user story:
   - TPRI ordering (primary)
   - Random ordering (averaged over 5 shuffles)
   - Severity-only ordering (ST score only, no CI/RC/FS)
4. Record results in comparison table.
5. Run ablation study: remove each factor in turn and measure APFD drop.

### 11.2 Expected comparison table

| User Story | TPRI APFD | Random APFD | ST-Only APFD |
|---|---|---|---|
| EXC-1 | — | — | — |
| EXC-2 | — | — | — |
| EXC-3 | — | — | — |
| Average | — | — | — |

Fill in with real values after Cypress execution.

### 11.3 Ablation study table

| Configuration | APFD | Drop from Full TPRI |
|---|---|---|
| Full TPRI (all 4 factors) | — | — |
| Without CI (α=0) | — | — |
| Without ST (β=0) | — | — |
| Without RC (γ=0) | — | — |
| Without FS (δ=0) | — | — |

The factor with the largest APFD drop is the strongest contributor to test prioritization effectiveness. Based on PORT 2.0 (Srikanth et al., 2015), CI (the equivalent of Fault Proneness) is predicted to have the largest drop.

### 11.4 RC reliability study

Before running the full evaluation, test the RC scoring prompt on 5 ACs from the fixture dataset:

1. Run the prompt on all 5 ACs. Record scores.
2. Run again 24 hours later. Record scores.
3. Calculate mean absolute difference between run 1 and run 2.
4. Ask one colleague to manually score the same 5 ACs from 0–1.
5. Calculate mean absolute difference between Claude scores and human scores.
6. Report both numbers. Target: both below 0.15.

This is reported in the Module 3 chapter as evidence of RC method reliability, citing Ardoğan et al. (2025) who identified consistency as the key challenge in LLM-based prioritization.

---

## 12. Configuration

All Module 3 configuration uses existing environment variables from `backend/config/settings.py`. No new environment variables are required.

| Variable | Default | Used by Module 3 for |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | RC scoring, test case generation, Cypress script generation |
| `CLAUDE_MODEL` | `claude-sonnet-4-5` | All Claude API calls |
| `CI_HIGH_THRESHOLD` | `0.80` | Filtering discrepancies before TPRI |
| `CI_MEDIUM_THRESHOLD` | `0.60` | Reference only — MEDIUM discrepancies excluded |
| `JIRA_BASE_URL` | — | Bug ticket creation (via existing jira_client) |
| `JIRA_EMAIL` | — | Bug ticket creation |
| `JIRA_API_TOKEN` | — | Bug ticket creation |
| `JIRA_PROJECT_KEY` | — | Bug ticket creation |

One new optional variable added to `.env` only (not to `settings.py`):

| Variable | Default | Purpose |
|---|---|---|
| `USE_MODULE_FIXTURES` | `true` | Enable/disable fixture fallback for development |

---

## 13. Error Handling

| Error scenario | Behaviour |
|---|---|
| Claude API call fails (RC scoring) | Log warning. Use RC = 0.5 as fallback. TPRI still computed. |
| Claude API call fails (test generation) | Log error. Return empty list for that AC. Other ACs unaffected. |
| Claude API call fails (Cypress script) | Log error. Skip that discrepancy. Mark tc as `cypress_script=None`. |
| Cypress not installed | Log warning. Return tests with `passed=None`, `confirmed_fault=None`. |
| Cypress script times out (>60s) | Log warning. Mark test as `passed=False`, `confirmed_fault=True`. |
| Jira bug creation fails | Log error. Continue. Set `jira_ticket=None` for that test. |
| Fixture file not found | Log warning. Return original inputs unchanged. |
| Module 2 returns MEDIUM/LOW only | TPRI computation returns empty list. Mode 2 skipped. Mode 1 still runs. |
| `app_url` is None | Mode 2 Cypress execution skipped. Mode 1 runs normally. |

---

## 14. Implementation Order

Implement files in this order. Each step is independently testable.

| Step | File | Test command |
|---|---|---|
| 1 | `fixtures/EXC-1_module1.json` | Open file, verify JSON valid |
| 2 | `fixtures/EXC-1_module2.json` | Open file, verify JSON valid |
| 3 | `fixture_loader.py` | Import and call with empty lists — confirm fixture loads |
| 4 | `tpri.py` | Call `compute_tpri()` with sample values — confirm score computes |
| 5 | `test_generator.py` (Mode 1 only) | Call `generate_coverage_tests()` — confirm Claude returns test cases |
| 6 | `test_generator.py` (Mode 2 only) | Call `generate_defect_tests()` — confirm Cypress scripts generated |
| 7 | `test_generator.py` (run_test_generator) | Call full function — confirm combined output |
| 8 | `docx_exporter.py` | Call `export_to_docx()` — confirm file created |
| 9 | `apfd_evaluator.py` | Call `compute_apfd()` with example data — confirm formula correct |
| 10 | `cypress_runner.py` | Call `run_cypress_tests()` with generated scripts |
| 11 | `test_module3_standalone.py` | `python -m backend.scripts.test_module3_standalone EXC-1` |
| 12 | Orchestrator edit | Start FastAPI, POST to `/api/jobs`, confirm `tests` in result |
| 13 | Fixtures EXC-2, EXC-3 | Repeat steps 11–12 for all three stories |
| 14 | Ablation study | `python -m backend.scripts.test_module3_standalone EXC-1 --ablation` |

---

## 15. Current State vs Planned State

| Area | Current state | After Module 3 implementation |
|---|---|---|
| `test_generator.py` | Stub — returns `[]` | Replaced — Mode 1 + Mode 2 generation with TPRI |
| `cypress_runner.py` | Stub — returns `[]` | Replaced — real Cypress execution in TPRI order |
| TPRI computation | Does not exist | `tpri.py` — full formula with CI/ST/RC/FS |
| Fixture fallback | Does not exist | `fixture_loader.py` — auto-detects stubs, loads JSON |
| DOCX export | Does not exist | `docx_exporter.py` — ranked test table in DOCX + MD |
| APFD evaluation | Does not exist | `apfd_evaluator.py` — APFD formula + ablation study |
| Anthropic API | Not wired anywhere | Wired in `tpri.py` and `test_generator.py` |
| Jira bug creation | Implemented in jira_client | Called by orchestrator after confirmed faults |
| Standalone runner | Does not exist | `test_module3_standalone.py` |

---

## 16. Summary

Module 3 introduces the Test Prioritization Risk Index (TPRI) as the research contribution of this module, extending prior work in requirement-based test case prioritization (Srikanth et al., 2015) by replacing manually-collected signals with automatically-computed AI-generated signals derived from the same pipeline that detected the discrepancies.

The implementation is contained entirely within `backend/pipeline/module3/` and `backend/scripts/fixtures/`. The only external change is two function calls updated in the existing orchestrator. No file belonging to Module 1 or Module 2 is modified.

The fixture-based development pattern ensures Module 3 is fully functional and independently testable from day one, regardless of the implementation status of the upstream modules.
