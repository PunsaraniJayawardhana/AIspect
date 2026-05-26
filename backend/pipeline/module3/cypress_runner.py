import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)


def run_cypress_tests(tests):
    updated = []

    for test in tests or []:
        if test.get("mode") != "defect_first" or test.get("cypress_script") is None:
            updated.append(test)
            continue

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                spec_path = os.path.join(tmpdir, f"{test['tc_id']}.cy.js")
                with open(spec_path, "w", encoding="utf-8") as handle:
                    handle.write(test["cypress_script"])

                result = subprocess.run(
                    ["npx", "cypress", "run", "--spec", spec_path, "--headless"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )

            if result.returncode == 0:
                test["passed"] = True
                test["confirmed_fault"] = False
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
            test["passed"] = False
            test["confirmed_fault"] = True
        except Exception as exc:
            logger.warning("Cypress execution failed for %s: %s", test["tc_id"], exc)
            test["passed"] = None
            test["confirmed_fault"] = None

        updated.append(test)

    return updated


def get_confirmed_faults(cypress_results):
    return [test for test in cypress_results or [] if test.get("confirmed_fault") is True]