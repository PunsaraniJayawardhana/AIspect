# Module 3 Current State

## Overview

Module 3 is the test-generation and execution layer of the AIspect pipeline. In its current implementation, it consumes the outputs from Module 1 and Module 2, generates test artifacts, optionally executes Cypress checks against a live application URL, and exports the results to DOCX, Markdown, and JSON.

## Current execution path

1. Module 3 receives:
   - `verified_discrepancies` from Module 2
   - `explicit_acs` and `implicit_acs` from Module 1
   - `story_text`
   - `story_key`
   - optional `app_url`
   - optional `nav_path`

2. It normalizes the acceptance criteria and combines explicit and implicit requirements.

3. It prioritizes discrepancies using TPRI scoring.

4. It generates:
   - **defect-first tests** when `app_url` is provided
   - **coverage-first tests** always

5. It exports artifacts.

6. If `app_url` is supplied, it runs Cypress and optionally creates Jira bugs for confirmed faults.

## Files involved

- `backend/pipeline/module3/test_generator.py`
- `backend/pipeline/module3/tpri.py`
- `backend/pipeline/module3/llm_client.py`
- `backend/pipeline/module3/cypress_runner.py`
- `backend/pipeline/module3/docx_exporter.py`
- `backend/pipeline/module3/apfd_evaluator.py`
- `backend/scripts/test_module3_standalone.py`
- `backend/pipeline/orchestrator.py`

## Inputs

### From Module 1

Module 3 receives:

- `explicit_acs`
- `implicit_acs`
- `story_text`
- `nav_path`

`get_module1_inputs()` is used to normalize and fill in missing values from fixtures when needed.

### From Module 2

Module 3 receives:

- `verified_discrepancies`

`get_module2_inputs()` is used to normalize values from fixtures.

## Internal processing

### 1. Acceptance criteria normalization

`_normalize_acs()` converts each acceptance criterion into a standardized structure:

- `ac_id`
- `text`
- `type`

This is used for both coverage-first and defect-first flows.

### 2. TPRI prioritization

`prioritize_discrepancies()` performs the following:

1. Collects all acceptance criterion texts.
2. Filters discrepancies using `CI_HIGH_THRESHOLD` unless the discrepancy is explicitly high confidence.
3. Computes TPRI for each remaining discrepancy using:
   - `ci`
   - `st`
   - `rc`
   - `fs`
4. Sorts by TPRI score and confidence.
5. Adds `priority_rank`.

### 3. TPRI computation

`compute_tpri()` combines:

- `ci`
- `st` from discrepancy type
- `rc` from `get_rc_score()`
- `fs` from `compute_fs()`

The score is weighted equally by default.

### 4. RC score generation

`get_rc_score()` asks the configured LLM provider to score the acceptance criterion on a 0.0 to 1.0 scale.

If the LLM call fails, it falls back to:

- `rc_score = 0.5`
- a fallback reasoning message

### 5. Feature similarity

`compute_fs()` computes feature similarity by comparing token sets between the current acceptance criterion and all other acceptance criteria.

This is a lightweight heuristic, not a semantic embedding model.

## Generation modes

### Coverage-first mode

This mode always runs.

For each normalized acceptance criterion, Module 3 prompts the LLM to generate:

- one positive test
- one negative test
- one boundary test

The prompt expects a JSON array.

If the LLM response is invalid, Module 3 falls back to a deterministic set of three test rows.

Each generated row becomes a test case with:

- `tc_id` in the form `TC-M1-###`
- `mode = coverage_first`
- `ticket_id`
- `ac_id`
- `scenario`
- `priority`
- `steps`
- `expected_result`

### Defect-first mode

This mode runs only when `app_url` is provided.

The prioritized discrepancies are converted into prompts for the LLM to generate a Cypress script.

If the LLM response is not a valid Cypress script, Module 3 falls back to a default Cypress script generated in code.

Each generated row becomes a test case with:

- `tc_id` in the form `TC-M2-###`
- `mode = defect_first`
- `ticket_id`
- `discrepancy_id`
- `requirement_id`
- `scenario`
- `priority`
- `steps`
- `expected_result`
- `cypress_script`

## Cypress execution

If `app_url` is provided, Module 3 calls `run_cypress_tests()`.

`run_cypress_tests()` is responsible for executing the generated Cypress scripts and returning a result structure.

The current orchestration flow then uses `get_confirmed_faults()` to identify confirmed failures and create Jira bugs.

## Exports

### DOCX export

`export_to_docx()` writes the generated tests to a DOCX file.

### Markdown export

`export_to_markdown()` writes the generated tests to a Markdown file.

### JSON export

The standalone runner writes JSON output to:

- `backend/scripts/fixtures/<story_key>_module3_output.json`

The JSON includes:

- `story_key`
- `tests`

## Standalone runner

`backend/scripts/test_module3_standalone.py` is the primary command-line entry point for testing Module 3 directly.

### Supported usage

- Basic run:

  `python -m backend.scripts.test_module3_standalone EXC-1`

- With app URL:

  `python -m backend.scripts.test_module3_standalone EXC-1 https://your-app-url`

- With ablation study:

  `python -m backend.scripts.test_module3_standalone EXC-1 https://your-app-url --ablation`

### What the standalone runner does

1. Resets the usage log.
2. Loads module inputs from fixtures.
3. Calls `run_test_generator()`.
4. Runs Cypress if `app_url` is present.
5. Exports artifacts.
6. Prints a summary.
7. Prints LLM usage statistics.

## LLM provider behavior

All LLM usage goes through `backend/pipeline/module3/llm_client.py`.

The current provider selection is controlled by `LLM_PROVIDER`:

- `anthropic`
- `groq`

The wrapper records usage metrics for each call and makes them available through `get_usage_summary()`.

## Usage tracking

A usage logger is active in the current implementation.

The standalone runner prints:

- number of LLM calls
- prompt tokens
- completion tokens
- total tokens
- provider breakdown

## Current limitations

- Module 1 and Module 2 are still partially stubbed.
- Module 3 can run end-to-end, but defect-first output quality depends on the quality of the upstream discrepancy data.
- The TPRI RC component depends on the configured LLM provider.
- The current implementation does not include a formal cost model beyond usage logging.

## Current output

When run with no `app_url`, Module 3 currently produces:

- coverage-first tests
- DOCX export
- Markdown export
- JSON output

When run with an `app_url`, Module 3 additionally produces:

- defect-first tests
- Cypress execution
- optional Jira bug creation for confirmed faults

## Summary

At the moment, Module 3 is a working test-generation and export layer that:

- consumes Module 1 and Module 2 outputs,
- prioritizes discrepancies with TPRI,
- generates both coverage-first and defect-first test artifacts,
- optionally executes Cypress,
- exports results, and
- logs LLM usage for the current run.
