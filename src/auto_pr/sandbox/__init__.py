"""Execution sandbox subsystem for Auto PR Control Plane."""

from auto_pr.sandbox.models import (
    CommandExecutionResult,
    SandboxSecurityViolation,
    CommandDisallowedError,
    PathTraversalError,
    ProtectedBranchError,
    DockerUnavailableError,
    SandboxExecutionTimeoutError,
)
from auto_pr.sandbox.base import ExecutionSandbox
from auto_pr.sandbox.security import (
    ALLOWED_BINARIES,
    DISALLOWED_BINARIES,
    validate_command,
    sanitize_environment,
    validate_path_containment,
)
from auto_pr.sandbox.worktree import LocalWorktreeSandbox
from auto_pr.sandbox.docker import DockerSandbox, is_docker_available

__all__ = [
    "CommandExecutionResult",
    "SandboxSecurityViolation",
    "CommandDisallowedError",
    "PathTraversalError",
    "ProtectedBranchError",
    "DockerUnavailableError",
    "SandboxExecutionTimeoutError",
    "ExecutionSandbox",
    "ALLOWED_BINARIES",
    "DISALLOWED_BINARIES",
    "validate_command",
    "sanitize_environment",
    "validate_path_containment",
    "LocalWorktreeSandbox",
    "DockerSandbox",
    "is_docker_available",
]
