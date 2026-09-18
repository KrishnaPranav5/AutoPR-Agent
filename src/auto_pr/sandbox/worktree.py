"""Local Git Worktree Sandbox implementation.

CRITICAL ARCHITECTURAL DISTINCTION:
A Git Worktree provides SOURCE-CONTROL ISOLATION (protecting default branches
like 'main' and uncommitted workspace changes from direct edits).
It does NOT provide container/jail process-level security isolation.
"""

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID

import psutil

from auto_pr.sandbox.base import ExecutionSandbox
from auto_pr.sandbox.models import (
    CommandExecutionResult,
    ProtectedBranchError,
    SandboxExecutionTimeoutError,
)
from auto_pr.sandbox.security import (
    validate_command,
    sanitize_environment,
)

logger = logging.getLogger(__name__)

PROTECTED_BRANCH_NAMES = frozenset([
    "main",
    "master",
    "prod",
    "production",
    "release",
    "stable",
])


class LocalWorktreeSandbox(ExecutionSandbox):
    """Execution sandbox using isolated Git worktrees."""

    def __init__(
        self,
        run_id: UUID,
        repo_path: Path,
        sandbox_base_dir: Path | None = None,
        branch_name: str | None = None,
        default_timeout_seconds: int = 120,
    ) -> None:
        super().__init__(
            run_id=run_id,
            repo_path=repo_path,
            sandbox_base_dir=sandbox_base_dir,
            branch_name=branch_name,
            default_timeout_seconds=default_timeout_seconds,
        )
        self.sandbox_dir = self.sandbox_base_dir / f"run_{str(self.run_id)[:8]}"

    async def create(self, base_branch: str = "main") -> Path:
        """Create a dedicated isolated git worktree on a non-protected branch."""
        # 1. Prevent protected branch mutations
        if self.branch_name.lower() in PROTECTED_BRANCH_NAMES:
            raise ProtectedBranchError(
                f"Cannot create sandbox on protected branch '{self.branch_name}'."
            )

        self.sandbox_base_dir.mkdir(parents=True, exist_ok=True)

        # Remove existing worktree dir if leftover from previous crashed run
        if self.sandbox_dir.exists():
            await self.cleanup()

        # 2. Add git worktree
        cmd = [
            "git",
            "worktree",
            "add",
            "-b",
            self.branch_name,
            str(self.sandbox_dir),
            base_branch,
        ]

        logger.info("Creating Git worktree at %s (branch: %s)", self.sandbox_dir, self.branch_name)
        result = subprocess.run(
            cmd,
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            # Check if branch already exists and checkout existing
            if "already exists" in result.stderr:
                cmd_existing = [
                    "git",
                    "worktree",
                    "add",
                    str(self.sandbox_dir),
                    self.branch_name,
                ]
                retry = subprocess.run(
                    cmd_existing,
                    cwd=str(self.repo_path),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if retry.returncode != 0:
                    raise RuntimeError(f"Failed to create git worktree: {retry.stderr.strip()}")
            else:
                raise RuntimeError(f"Failed to create git worktree: {result.stderr.strip()}")

        self._is_prepared = True
        return self.sandbox_dir

    async def prepare(self) -> None:
        """Prepare worktree (validates creation)."""
        if not self.sandbox_dir or not self.sandbox_dir.is_dir():
            raise RuntimeError("Sandbox directory does not exist. Call create() first.")
        self._is_prepared = True

    async def execute_command(
        self,
        command: Sequence[str] | str,
        cwd: Path | str | None = None,
        timeout_seconds: int | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandExecutionResult:
        """Execute a validated command with environment sanitization and process termination."""
        if not self._is_prepared or not self.sandbox_dir:
            raise RuntimeError("Sandbox has not been created or prepared.")

        # 1. Defense-in-depth: Validate command allowlisting and reject shell injection
        cmd_tokens = validate_command(command)

        # Resolve python/pytest binary to active environment interpreter
        import sys
        binary_lower = cmd_tokens[0].lower()
        if binary_lower in ("python", "python3", "py"):
            cmd_tokens[0] = sys.executable
        elif binary_lower == "pytest":
            venv_pytest = shutil.which("pytest", path=str(Path(sys.executable).parent))
            if venv_pytest:
                cmd_tokens[0] = venv_pytest

        # 2. Defense-in-depth: Path traversal check on working directory
        effective_cwd = (
            self.validate_path(cwd)
            if cwd
            else self.sandbox_dir
        )

        # 3. Defense-in-depth: Sanitize environment (strips host credentials and secrets)
        clean_env = sanitize_environment(env)
        # Ensure virtual environment or current python is accessible
        clean_env["VIRTUAL_ENV"] = str(Path(sys.executable).parent.parent)

        timeout = timeout_seconds or self.default_timeout_seconds
        start_time = time.perf_counter()
        timed_out = False
        stdout = ""
        stderr = ""
        exit_code = -1

        logger.debug("Executing sandbox command: %s (cwd=%s)", cmd_tokens, effective_cwd)

        process = None
        try:
            process = subprocess.Popen(
                cmd_tokens,
                cwd=str(effective_cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=clean_env,
                text=True,
                shell=False,  # Enforce structured execution (no shell)
            )

            stdout, stderr = process.communicate(timeout=timeout)
            exit_code = process.returncode

        except subprocess.TimeoutExpired:
            timed_out = True
            logger.warning("Command '%s' timed out after %ds. Terminating process tree.", cmd_tokens, timeout)
            if process:
                self._terminate_process_tree(process.pid)
                try:
                    stdout, stderr = process.communicate(timeout=2)
                except Exception:
                    pass
            exit_code = -1

        except Exception as exc:
            stderr = f"Process execution failed: {exc}"
            exit_code = -1

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        return CommandExecutionResult(
            command=cmd_tokens,
            working_dir=str(effective_cwd),
            exit_code=exit_code,
            stdout=stdout or "",
            stderr=stderr or "",
            duration_ms=duration_ms,
            timed_out=timed_out,
            environment_redacted=True,
        )

    def _terminate_process_tree(self, pid: int) -> None:
        """Terminate a process and all of its descendants cleanly using psutil."""
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            parent.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    async def cleanup(self) -> None:
        """Remove git worktree and clean up the ephemeral branch."""
        if not self.sandbox_dir:
            return

        logger.info("Cleaning up Git worktree at %s", self.sandbox_dir)

        # Remove git worktree
        if self.sandbox_dir.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(self.sandbox_dir)],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                check=False,
            )
            # If filesystem directory still remains, remove it
            if self.sandbox_dir.exists():
                shutil.rmtree(self.sandbox_dir, ignore_errors=True)

        # Prune worktree metadata
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(self.repo_path),
            capture_output=True,
            text=True,
            check=False,
        )

        # Delete ephemeral branch if created
        if self.branch_name and self.branch_name.lower() not in PROTECTED_BRANCH_NAMES:
            subprocess.run(
                ["git", "branch", "-D", self.branch_name],
                cwd=str(self.repo_path),
                capture_output=True,
                text=True,
                check=False,
            )

        self._is_prepared = False

    def get_metadata(self) -> dict[str, Any]:
        """Return sandbox metadata with explicit isolation level disclaimer."""
        return {
            "sandbox_type": "worktree",
            "isolation_level": "source_control_isolation",
            "description": "Git worktree source-control isolation (Not a container/process jail)",
            "sandbox_dir": str(self.sandbox_dir),
            "branch_name": self.branch_name,
            "run_id": str(self.run_id),
        }
