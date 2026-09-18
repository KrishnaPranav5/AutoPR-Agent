"""Data models and exception hierarchy for sandbox execution."""

from typing import Any
from pydantic import BaseModel, Field


class CommandExecutionResult(BaseModel):
    """Execution evidence produced by running a command in a sandbox."""

    command: list[str]
    working_dir: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    environment_redacted: bool = True


class SandboxSecurityViolation(Exception):
    """Base exception for sandbox security violations."""


class CommandDisallowedError(SandboxSecurityViolation):
    """Raised when a command is rejected by security allowlisting."""


class PathTraversalError(SandboxSecurityViolation):
    """Raised when a file or directory path attempts to escape the sandbox root."""


class ProtectedBranchError(SandboxSecurityViolation):
    """Raised when a sandbox attempts to use or modify a protected Git branch."""


class DockerUnavailableError(Exception):
    """Raised when Docker container sandbox is requested but Docker daemon is not active."""


class SandboxExecutionTimeoutError(Exception):
    """Raised when a sandbox command exceeds configured execution timeout."""
