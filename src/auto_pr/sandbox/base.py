"""Abstract Execution Sandbox protocol.

Provides a unified interface for both LocalWorktreeSandbox and DockerSandbox.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Sequence
from uuid import UUID

from auto_pr.sandbox.models import CommandExecutionResult
from auto_pr.sandbox.security import validate_path_containment


class ExecutionSandbox(ABC):
    """Abstract interface for isolated execution environments."""

    def __init__(
        self,
        run_id: UUID,
        repo_path: Path,
        sandbox_base_dir: Path | None = None,
        branch_name: str | None = None,
        default_timeout_seconds: int = 120,
    ) -> None:
        self.run_id = run_id
        self.repo_path = Path(repo_path).resolve()
        self.sandbox_base_dir = (
            Path(sandbox_base_dir).resolve()
            if sandbox_base_dir
            else self.repo_path / ".auto_pr_worktrees"
        )
        self.branch_name = branch_name or f"auto-pr/run-{str(run_id)[:8]}"
        self.default_timeout_seconds = default_timeout_seconds
        self.sandbox_dir: Path | None = None
        self._is_prepared: bool = False

    @abstractmethod
    async def create(self, base_branch: str = "main") -> Path:
        """Create and initialize the isolated workspace."""
        ...

    @abstractmethod
    async def prepare(self) -> None:
        """Prepare execution dependencies or container environment."""
        ...

    @abstractmethod
    async def execute_command(
        self,
        command: Sequence[str] | str,
        cwd: Path | str | None = None,
        timeout_seconds: int | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandExecutionResult:
        """Execute a validated command inside the sandbox environment."""
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        """Tear down and remove the sandbox workspace."""
        ...

    @abstractmethod
    def get_metadata(self) -> dict[str, Any]:
        """Return sandbox metadata (type, path, isolation level, branch)."""
        ...

    def validate_path(self, target_path: Path | str) -> Path:
        """Ensure path does not escape the sandbox root."""
        if not self.sandbox_dir:
            raise RuntimeError("Sandbox workspace has not been created yet.")
        return validate_path_containment(target_path, self.sandbox_dir)
