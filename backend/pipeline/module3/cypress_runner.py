import logging
import os
import platform
import subprocess
import asyncio

CYPRESS_PROJECT_DIR = os.environ.get("CYPRESS_PROJECT_DIR")

logger = logging.getLogger(__name__)

# Execution errors mean the generated Cypress test file itself could not run.
EXECUTION_ERROR_MARKERS = (
    "cannot find module", "no tests found", "cypress could not verify",
    "config file", "syntaxerror", "referenceerror",
    "webpack compilation error", "error preparing this test file",
    "module build failed", "unterminated string constant", "unexpected token",
)

# Connection errors mean the test runner started, but the target app was unreachable.
CONNECTION_ERROR_MARKERS = (
    "econnrefused",
    "failed trying to load",
    "we attempted to make an http request",
    "failed to establish a connection",
    "cy.visit()",
    "net::err_connection_refused",
    "the request failed without a response",
    "connection was reset",
    "err_connection",
    "socket hang up",
    "timed out waiting for the server",
)


def _is_execution_error(output: str) -> bool:
    lowered = (output or "").lower()
    return any(marker in lowered for marker in EXECUTION_ERROR_MARKERS)


def _is_connection_error(output: str) -> bool:
    lowered = (output or "").lower()
    return any(marker in lowered for marker in CONNECTION_ERROR_MARKERS)


def _build_spec_path(test):
    spec_dir = os.path.join(CYPRESS_PROJECT_DIR, "cypress", "e2e", "aispect_generated")
    os.makedirs(spec_dir, exist_ok=True)
    return os.path.join(spec_dir, f"{test['tc_id']}.cy.js")


def _run_single_cypress_spec(spec_path):
    use_shell = platform.system() == "Windows"
    return subprocess.run(
        ["npx", "cypress", "run", "--spec", spec_path, "--headless"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
        cwd=CYPRESS_PROJECT_DIR,
        shell=use_shell,
    )


def _apply_cypress_result(test, result):
    if result.returncode == 0:
        test["passed"] = True
        test["confirmed_fault"] = False
        return

    combined_output = "\n".join(filter(None, [result.stderr, result.stdout]))
    if _is_execution_error(combined_output):
        logger.warning(
            "Cypress execution error (not a real defect) for %s: %s",
            test["tc_id"],
            combined_output,
        )
        test["passed"] = None
        test["confirmed_fault"] = None
        return

    if _is_connection_error(combined_output):
        logger.warning(
            "Cypress could not reach the target app (connection issue) for %s: %s",
            test["tc_id"],
            combined_output,
        )
        test["passed"] = None
        test["confirmed_fault"] = None
        return

    test["passed"] = False
    test["confirmed_fault"] = True
    logger.warning("Cypress run failed for %s: %s", test["tc_id"], result.stderr or result.stdout)


def _handle_non_defect_test(test, defects_only, updated):
    if test.get("mode") != "defect_first":
        if not defects_only:
            updated.append(test)
        return True
    return False


def _handle_missing_script(test, updated):
    if test.get("cypress_script") is not None:
        return False
    test["passed"] = None
    test["confirmed_fault"] = None
    test["execution_note"] = "Skipped: missing cypress_script"
    updated.append(test)
    return True


def _execute_one_test(test):
    spec_path = _build_spec_path(test)
    try:
        with open(spec_path, "w", encoding="utf-8") as handle:
            handle.write(test["cypress_script"])

        result = _run_single_cypress_spec(spec_path)
        _apply_cypress_result(test, result)

    except FileNotFoundError:
        logger.warning("npx is not available; Cypress execution skipped for %s", test["tc_id"])
        test["passed"] = None
        test["confirmed_fault"] = None
    except subprocess.TimeoutExpired:
        logger.warning("Cypress run timed out for %s", test["tc_id"])
        test["passed"] = None
        test["confirmed_fault"] = None
    except Exception as exc:
        logger.warning("Cypress execution failed for %s: %s", test["tc_id"], exc)
        test["passed"] = None
        test["confirmed_fault"] = None
    finally:
        if os.path.exists(spec_path):
            os.remove(spec_path)


def run_cypress_tests(tests, defects_only=False):
    updated = []

    for test in tests or []:
        if _handle_non_defect_test(test, defects_only, updated):
            continue

        if _handle_missing_script(test, updated):
            continue

        _execute_one_test(test)

        updated.append(test)

    return updated


def get_confirmed_faults(cypress_results):
    return [test for test in cypress_results or [] if test.get("confirmed_fault") is True]


async def execute_cypress(tests, app_url=None):
    """Async wrapper expected by orchestrator; runs sync Cypress runner in a thread."""
    del app_url
    return await asyncio.to_thread(run_cypress_tests, tests, True)
