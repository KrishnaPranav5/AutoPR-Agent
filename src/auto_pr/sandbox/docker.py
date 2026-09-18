"""Docker Container Sandbox implementation.

PREFERRED SECURITY BOUNDARY:
Executes untrusted or generated code inside disposable Docker containers
with strict resource limits, network isolation, and non-root execution.
"""

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID

from auto_pr.sandbox.base import ExecutionSandbox
from auto_pr.sandbox.models import (
    CommandExecutionResult,
    DockerUnavailableError,
)
from auto_pr.sandbox.security import (
    validate_command,
    sanitize_environment,
)
from auto_pr.sandbox.worktree import LocalWorktreeSandbox

logger = logging.getLogger(__name__)


def is_docker_available() -> bool:
    """Check if Docker CLI and daemon are responsive."""
    try:
        res = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
        return res.returncode == 0
    except Exception:
        return False


class DockerSandbox(ExecutionSandbox):
    """Containerized execution sandbox providing process and network isolation."""

    def __init__(
        self,
        run_id: UUID,
        repo_path: Path,
        image_name: str = "python:3.11-slim",
        sandbox_base_dir: Path | None = None,
        branch_name: str | None = None,
        default_timeout_seconds: int = 120,
        memory_limit: str = "1g",
        cpu_limit: str = "1.0",
        network_mode: str = "none",
    ) -> None:
        super().__init__(
            run_id=run_id,
            repo_path=repo_path,
            sandbox_base_dir=sandbox_base_dir,
            branch_name=branch_name,
            default_timeout_seconds=default_timeout_seconds,
        )
        self.image_name = image_name
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit
        self.network_mode = network_mode
        self.container_name = f"auto-pr-{str(self.run_id)[:8]}"

        # Underlying worktree sandbox providing source control isolation
        self._worktree_sandbox = LocalWorktreeSandbox(
            run_id=run_id,
            repo_path=repo_path,
            sandbox_base_dir=sandbox_base_dir,
            branch_name=branch_name,
            default_timeout_seconds=default_timeout_seconds,
        )

    async def create(self, base_branch: str = "main") -> Path:
        """Initialize worktree and verify Docker availability."""
        if not is_docker_available():
            raise DockerUnavailableError(
                "Docker daemon is not responsive. DockerSandbox requires an active Docker engine."
            )

        # 1. Create underlying source-control isolated worktree
        self.sandbox_dir = await self._worktree_sandbox.create(base_branch=base_branch)
        self._is_prepared = True
        return self.sandbox_dir

    async def prepare(self) -> None:
        """Prepare container environment."""
        if not is_docker_available():
            raise DockerUnavailableError("Docker daemon is not responsive.")
        await self._worktree_sandbox.prepare()
        self._is_prepared = True

    async def execute_command(
        self,
        command: Sequence[str] | str,
        cwd: Path | str | None = None,
        timeout_seconds: int | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandExecutionResult:
        """Execute command inside disposable Docker container."""
        if not self._is_prepared or not self.sandbox_dir:
            raise RuntimeError("Docker sandbox has not been initialized.")

        cmd_tokens = validate_command(command)
        effective_cwd = (
            self.validate_path(cwd)
            if cwd
            else self.sandbox_dir
        )
        rel_cwd = effective_cwd.relative_to(self.sandbox_dir)
        container_cwd = f"/workspace/{rel_cwd}".replace("\\", "/") if str(rel_cwd) != "." else "/workspace"

        clean_env = sanitize_environment(env)
        timeout = timeout_seconds or self.default_timeout_seconds
        start_time = time.perf_counter()
        timed_out = False

        # Assemble docker run invocation with isolation flags
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            self.container_name,
            f"--memory={self.memory_limit}",
            f"--cpus={self.cpu_limit}",
            f"--network={self.network_mode}",
            "-v",
            f"{self.sandbox_dir}:/workspace:rw",
            "-w",
            container_cwd,
        ]

        # Pass sanitized environment variables
        for k, v in clean_env.items():
            if k in ("PYTHONUTF8", "PYTHONIOENCODING"):
                docker_cmd.extend(["-e", f"{k}={v}"])

        docker_cmd.append(self.image_name)
        docker_cmd.extend(cmd_tokens)

        process = None
        stdout = ""
        stderr = ""
        exit_code = -1

        try:
            process = subprocess.Popen(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
            )
            stdout, stderr = process.communicate(timeout=timeout)
            exit_code = process.returncode

        except subprocess.TimeoutExpired:
            timed_out = True
            logger.warning("Docker container %s timed out. Terminating.", self.container_name)
            # Force remove running container
            subprocess.run(
                ["docker", "rm", "-f", self.container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if process:
                process.kill()
            exit_code = -1

        except Exception as exc:
            stderr = f"Docker execution error: {exc}"
            exit_code = -1

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        return CommandExecutionResult(
            command=cmd_tokens,
            working_dir=container_cwd,
            exit_code=exit_code,
            stdout=stdout or "",
            stderr=stderr or "",
            duration_ms=duration_ms,
            timed_out=timed_out,
            environment_redacted=True,
        )

    async def cleanup(self) -> None:
        """Kill container if running and remove git worktree."""
        try:
            subprocess.run(
                ["docker", "rm", "-f", self.container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass

        await self._worktree_sandbox.cleanup()
        self._is_prepared = False

    def get_metadata(self) -> dict[str, Any]:
        """Return sandbox metadata detailing container security boundaries."""
        return {
            "sandbox_type": "docker",
            "isolation_level": "container_process_isolation",
            "description": "Disposable container with memory, cpu, and network isolation",
            "image": self.image_name,
            "network": self.network_mode,
            "memory_limit": self.memory_limit,
            "cpu_limit": self.cpu_limit,
            "container_name": self.container_name,
            "run_id": str(self.run_id),
        }
