import logging
import os
import platform
import subprocess
import asyncio

CYPRESS_PROJECT_DIR = os.environ.get("CYPRESS_PROJECT_DIR")

logger = logging.getLogger(__name__)


def run_cypress_tests(tests):
    updated = []

    for test in tests or []:
        if test.get("mode") != "defect_first" or test.get("cypress_script") is None:
            updated.append(test)
            continue

        use_shell = platform.system() == "Windows"
        spec_dir = os.path.join(CYPRESS_PROJECT_DIR, "cypress", "e2e", "aispect_generated")
        os.makedirs(spec_dir, exist_ok=True)
        spec_path = os.path.join(spec_dir, f"{test['tc_id']}.cy.js")

        try:
            with open(spec_path, "w", encoding="utf-8") as handle:
                handle.write(test["cypress_script"])

            result = subprocess.run(
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

            if result.returncode == 0:
                test["passed"] = True
                test["confirmed_fault"] = False
            else:
                stderr_lower = (result.stderr or "").lower()
                execution_error_markers = (
                    "cannot find module", "no tests found", "cypress could not verify",
                    "config file", "syntaxerror", "referenceerror",
                )
                if any(marker in stderr_lower for marker in execution_error_markers):
                    logger.warning("Cypress execution error (not a real defect) for %s: %s", test["tc_id"], result.stderr)
                    test["passed"] = None
                    test["confirmed_fault"] = None
                else:
                    test["passed"] = False
                    test["confirmed_fault"] = True
                    logger.warning("Cypress run failed for %s: %s", test["tc_id"], result.stderr or result.stdout)

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

        updated.append(test)

    return updated


def get_confirmed_faults(cypress_results):
    return [test for test in cypress_results or [] if test.get("confirmed_fault") is True]


async def execute_cypress(tests, app_url=None):
    """Async wrapper expected by orchestrator; runs sync Cypress runner in a thread."""
    return await asyncio.to_thread(run_cypress_tests, tests)