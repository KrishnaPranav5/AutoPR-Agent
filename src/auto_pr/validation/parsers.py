"""Parsers for test results, tracebacks, and failure diagnostic information."""

import re
from pydantic import BaseModel, Field


class FailureDetails(BaseModel):
    """Structured diagnostic failure information for the Debugging Agent."""

    failing_command: str
    exit_code: int
    failure_type: str = "UNKNOWN_FAILURE"
    failing_tests: list[str] = Field(default_factory=list)
    likely_failure_location: str | None = None
    summary: str = ""


class ValidationFailureParser:
    """Extracts failure locations, test names, and classifications from test runner outputs."""

    # Pytest failure patterns: FAILED tests/test_foo.py::test_bar - AssertionError
    PYTEST_FAIL_PATTERN = re.compile(r"FAILED\s+([^\s:]+::[^\s\n]+)")
    # Python traceback file pattern: File "...", line 123, in foo
    TRACEBACK_FILE_PATTERN = re.compile(r'File "([^"]+)", line (\d+)')
    # Pytest short trace pattern: tests/test_calc.py:15: AssertionError
    SHORT_TRACE_PATTERN = re.compile(r"([A-Za-z0-9_\-/\\]+\.py):(\d+):\s+([A-Za-z0-9_]+Error)")
    # Lint error pattern: src/foo.py:10:5: E...
    LINT_ERROR_PATTERN = re.compile(r"([A-Za-z0-9_\-/\\]+\.py):(\d+):(?:\d+:)?\s+([A-Za-z0-9_]+)")

    def parse_failure(
        self,
        command: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        timed_out: bool = False,
    ) -> FailureDetails:
        """Analyze raw execution output and produce structured failure diagnostics."""
        combined_text = f"{stdout}\n{stderr}"

        if timed_out:
            return FailureDetails(
                failing_command=command,
                exit_code=exit_code,
                failure_type="TIMEOUT",
                summary=f"Command '{command}' timed out during execution.",
            )

        # 1. Detect failure type
        failure_type = "UNKNOWN_FAILURE"
        if "SyntaxError" in combined_text:
            failure_type = "SYNTAX_ERROR"
        elif "AssertionError" in combined_text or "FAILED" in combined_text:
            failure_type = "ASSERTION_FAILURE"
        elif "ImportError" in combined_text or "ModuleNotFoundError" in combined_text:
            failure_type = "IMPORT_ERROR"
        elif "TypeError" in combined_text:
            failure_type = "TYPE_ERROR"
        elif "ruff" in command or "flake8" in command or "mypy" in command:
            failure_type = "LINT_ERROR"

        # 2. Extract failing test names
        failing_tests = self.PYTEST_FAIL_PATTERN.findall(combined_text)

        # 3. Locate likely failure location (file:line)
        likely_location = None
        short_match = self.SHORT_TRACE_PATTERN.search(combined_text)
        if short_match:
            likely_location = f"{short_match.group(1)}:{short_match.group(2)}"
        else:
            tb_matches = self.TRACEBACK_FILE_PATTERN.findall(combined_text)
            if tb_matches:
                # Prefer the last application file in the traceback
                app_matches = [m for m in tb_matches if not m[0].startswith("<") and "site-packages" not in m[0]]
                if app_matches:
                    likely_location = f"{app_matches[-1][0]}:{app_matches[-1][1]}"
                else:
                    likely_location = f"{tb_matches[-1][0]}:{tb_matches[-1][1]}"
            else:
                lint_match = self.LINT_ERROR_PATTERN.search(combined_text)
                if lint_match:
                    likely_location = f"{lint_match.group(1)}:{lint_match.group(2)}"

        summary_lines = []
        if failing_tests:
            summary_lines.append(f"Failing tests: {', '.join(failing_tests[:3])}")
        if likely_location:
            summary_lines.append(f"Failure location: {likely_location}")
        if not summary_lines:
            summary_lines.append(f"Command '{command}' exited with code {exit_code}")

        return FailureDetails(
            failing_command=command,
            exit_code=exit_code,
            failure_type=failure_type,
            failing_tests=failing_tests,
            likely_failure_location=likely_location,
            summary="; ".join(summary_lines),
        )
