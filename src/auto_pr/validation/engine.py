"""Validation Engine.

Executes real test and build commands through an isolated sandbox.
ONLY REAL SUBPROCESS EXECUTION PRODUCES VALIDATION EVIDENCE.
An LLM claim is NEVER treated as execution evidence.
"""

import logging
from typing import Sequence

from auto_pr.core.models import ValidationRun, ValidationCommandResult
from auto_pr.discovery.models import DiscoveredCommands
from auto_pr.sandbox.base import ExecutionSandbox
from auto_pr.validation.parsers import ValidationFailureParser, FailureDetails

logger = logging.getLogger(__name__)


class ValidationEngine:
    """Orchestrates actual validation execution and collects verifiable evidence."""

    def __init__(self, failure_parser: ValidationFailureParser | None = None) -> None:
        self.failure_parser = failure_parser or ValidationFailureParser()

    async def run_validation(
        self,
        sandbox: ExecutionSandbox,
        commands: Sequence[str] | DiscoveredCommands,
        iteration: int = 1,
        timeout_seconds: int | None = None,
    ) -> tuple[ValidationRun, FailureDetails | None]:
        """Execute validation commands inside the sandbox and capture execution results.

        Returns:
            tuple of (ValidationRun, optional FailureDetails)
        """
        command_list = self._resolve_commands(commands)
        if not command_list:
            raise ValueError("No validation commands provided.")

        command_results: list[ValidationCommandResult] = []
        total_duration_ms = 0
        all_passed = True
        failure_details: FailureDetails | None = None
        failure_summaries: list[str] = []

        logger.info(
            "Starting validation run (iteration %d) with %d commands on sandbox %s",
            iteration,
            len(command_list),
            sandbox.get_metadata().get("sandbox_type"),
        )

        for cmd_str in command_list:
            exec_result = await sandbox.execute_command(
                cmd_str,
                timeout_seconds=timeout_seconds,
            )

            total_duration_ms += exec_result.duration_ms
            passed = exec_result.exit_code == 0 and not exec_result.timed_out

            cmd_record = ValidationCommandResult(
                command=" ".join(exec_result.command),
                exit_code=exec_result.exit_code,
                stdout=exec_result.stdout,
                stderr=exec_result.stderr,
                duration_ms=exec_result.duration_ms,
                passed=passed,
            )
            command_results.append(cmd_record)

            if not passed:
                all_passed = False
                # Parse structured failure details for the debugging agent
                parsed_failure = self.failure_parser.parse_failure(
                    command=" ".join(exec_result.command),
                    exit_code=exec_result.exit_code,
                    stdout=exec_result.stdout,
                    stderr=exec_result.stderr,
                    timed_out=exec_result.timed_out,
                )
                if failure_details is None:
                    failure_details = parsed_failure
                failure_summaries.append(parsed_failure.summary)
                # Fail fast on test suite failure
                break

        val_run = ValidationRun(
            iteration=iteration,
            command_results=command_results,
            all_passed=all_passed,
            duration_ms=total_duration_ms,
            failure_summary="; ".join(failure_summaries) if failure_summaries else None,
        )

        return val_run, failure_details

    def _resolve_commands(
        self,
        commands: Sequence[str] | DiscoveredCommands,
    ) -> list[str]:
        """Extract ordered list of commands to run (lint/typecheck -> test)."""
        if isinstance(commands, DiscoveredCommands):
            cmd_list = []
            if commands.lint_command:
                cmd_list.append(commands.lint_command)
            if commands.typecheck_command:
                cmd_list.append(commands.typecheck_command)
            if commands.test_command:
                cmd_list.append(commands.test_command)
            return cmd_list

        return list(commands)
