import asyncio
from types import SimpleNamespace

from backend.pipeline.module3 import cypress_runner


def test_execute_cypress_runs_non_defect_tests_by_default(monkeypatch):
    seen = {}

    def fake_run_cypress_tests(tests, defects_only=False):
        seen["tests"] = tests
        seen["defects_only"] = defects_only
        return tests

    monkeypatch.setattr(cypress_runner, "run_cypress_tests", fake_run_cypress_tests)

    tests = [
        {"tc_id": "TC-01", "mode": "defect_first"},
        {"tc_id": "TC-02", "mode": "coverage_first"},
    ]

    result = asyncio.run(cypress_runner.execute_cypress(tests, app_url="http://example.test"))

    assert result == tests
    assert seen["defects_only"] is False


def test_run_cypress_tests_falls_back_to_repo_root_when_project_dir_missing(monkeypatch):
    monkeypatch.setattr(cypress_runner, "CYPRESS_PROJECT_DIR", None)

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cypress_runner.subprocess, "run", fake_run)

    test = {
        "tc_id": "TC-03",
        "mode": "defect_first",
        "cypress_script": "describe('demo', () => { it('works', () => {}); });",
    }

    result = cypress_runner.run_cypress_tests([test])

    assert result[0]["passed"] is True
    assert result[0]["confirmed_fault"] is False


def test_invalid_timeout_environment_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CYPRESS_RUN_TIMEOUT_SECONDS", "not-a-number")
    monkeypatch.setenv("CYPRESS_HOLD_SECONDS", "0")

    assert cypress_runner._get_cypress_run_timeout_seconds() == 120
    assert cypress_runner._get_cypress_hold_seconds() == 0


def test_run_cypress_tests_executes_coverage_tests_by_default(monkeypatch):
    executed = []

    def fake_execute_one_test(test):
        executed.append(test["tc_id"])

    monkeypatch.setattr(cypress_runner, "_execute_one_test", fake_execute_one_test)

    tests = [
        {"tc_id": "TC-M2-001", "mode": "defect_first", "cypress_script": "describe('x', () => { it('y', () => {}); });"},
        {"tc_id": "TC-M1-001", "mode": "coverage_first", "cypress_script": "describe('x', () => { it('y', () => {}); });"},
    ]

    result = cypress_runner.run_cypress_tests(tests)

    assert [item["tc_id"] for item in result] == ["TC-M2-001", "TC-M1-001"]
    assert executed == ["TC-M2-001", "TC-M1-001"]


def test_execute_cypress_can_request_defect_only_mode(monkeypatch):
    seen = {}

    def fake_run_cypress_tests(tests, defects_only=False):
        seen["tests"] = tests
        seen["defects_only"] = defects_only
        return tests

    monkeypatch.setattr(cypress_runner, "run_cypress_tests", fake_run_cypress_tests)

    tests = [{"tc_id": "TC-04", "mode": "defect_first"}]

    result = asyncio.run(cypress_runner.execute_cypress(tests, app_url="http://example.test", defects_only=True))

    assert result == tests
    assert seen["defects_only"] is True
