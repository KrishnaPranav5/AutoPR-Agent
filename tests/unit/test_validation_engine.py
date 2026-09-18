"""Unit tests for ValidationEngine, real execution verification, and failure diagnostic parsing."""

from pathlib import Path
import subprocess
import uuid
import pytest

from auto_pr.sandbox.worktree import LocalWorktreeSandbox
from auto_pr.validation.engine import ValidationEngine
from auto_pr.validation.parsers import ValidationFailureParser


@pytest.fixture
def repo_with_tests(tmp_path: Path) -> Path:
    """Initialize a git repo with a passing test and a failing test."""
    repo_dir = tmp_path / "val_repo"
    repo_dir.mkdir()

    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Runner"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_dir), check=True)

    src = repo_dir / "src"
    src.mkdir()
    (src / "calculator.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")

    tests = repo_dir / "tests"
    tests.mkdir()
    (tests / "test_calc.py").write_text(
        "from src.calculator import add\n\n"
        "def test_add_pass():\n    assert add(1, 2) == 3\n\n"
        "def test_add_fail():\n    assert add(2, 2) == 5\n",
        encoding="utf-8",
    )

    (repo_dir / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n', encoding="utf-8")

    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "add calc and tests"], cwd=str(repo_dir), check=True)

    return repo_dir


@pytest.mark.asyncio
async def test_successful_validation(repo_with_tests: Path) -> None:
    """Verify that a passing test command produces a passing ValidationRun."""
    run_id = uuid.uuid4()
    sandbox = LocalWorktreeSandbox(run_id=run_id, repo_path=repo_with_tests)
    await sandbox.create()

    engine = ValidationEngine()
    # Execute only the passing test: pytest -k test_add_pass
    pass_cmd = "python -m pytest -k test_add_pass"
    val_run, failure = await engine.run_validation(sandbox, [pass_cmd], iteration=1)

    assert val_run.all_passed is True
    assert len(val_run.command_results) == 1
    assert val_run.command_results[0].passed is True
    assert val_run.command_results[0].exit_code == 0
    assert failure is None

    await sandbox.cleanup()


@pytest.mark.asyncio
async def test_failed_validation_and_trace_parsing(repo_with_tests: Path) -> None:
    """Verify that a failing test execution produces structured failure diagnostics."""
    run_id = uuid.uuid4()
    sandbox = LocalWorktreeSandbox(run_id=run_id, repo_path=repo_with_tests)
    await sandbox.create()

    engine = ValidationEngine()
    # Execute the failing test: pytest -k test_add_fail
    fail_cmd = "python -m pytest -k test_add_fail"
    val_run, failure = await engine.run_validation(sandbox, [fail_cmd], iteration=1)

    assert val_run.all_passed is False
    assert len(val_run.command_results) == 1
    assert val_run.command_results[0].passed is False
    assert val_run.command_results[0].exit_code != 0

    # Verify structured failure diagnostics
    assert failure is not None
    assert failure.failure_type == "ASSERTION_FAILURE"
    assert any("test_add_fail" in t for t in failure.failing_tests)
    assert failure.likely_failure_location is not None
    assert "test_calc.py" in failure.likely_failure_location

    await sandbox.cleanup()


@pytest.mark.asyncio
async def test_validation_timeout(repo_with_tests: Path) -> None:
    """Verify that a timing out validation command flags timeout failure."""
    run_id = uuid.uuid4()
    sandbox = LocalWorktreeSandbox(run_id=run_id, repo_path=repo_with_tests)
    await sandbox.create()

    engine = ValidationEngine()
    timeout_cmd = "python -c import(time);time.sleep(10)"  # intentional command that will time out
    timeout_tokens = ["python", "-c", "import time; time.sleep(10)"]
    val_run, failure = await engine.run_validation(sandbox, [timeout_tokens], timeout_seconds=1)

    assert val_run.all_passed is False
    assert failure is not None
    assert failure.failure_type == "TIMEOUT"
    assert "timed out" in failure.summary

    await sandbox.cleanup()


def test_failure_parser_diagnostics() -> None:
    """Verify parser extracts failing tests and files from mock pytest outputs."""
    parser = ValidationFailureParser()
    mock_stdout = (
        "============================= FAILURES =============================\n"
        "___________________________ test_multiply ___________________________\n"
        "tests/unit/test_calc.py:25: in test_multiply\n"
        "    assert Calculator().multiply(2, 3) == 10\n"
        "E   AssertionError: assert 6 == 10\n"
        "=========================== short test summary info ===========================\n"
        "FAILED tests/unit/test_calc.py::test_multiply - AssertionError: assert 6 == 10\n"
        "======================== 1 failed, 10 passed in 0.45s ========================="
    )

    details = parser.parse_failure("pytest tests/", 1, mock_stdout, "")
    assert details.failure_type == "ASSERTION_FAILURE"
    assert "tests/unit/test_calc.py::test_multiply" in details.failing_tests
    assert details.likely_failure_location == "tests/unit/test_calc.py:25"
