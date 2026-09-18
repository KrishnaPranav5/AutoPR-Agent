"""Base class and execution contracts for specialized agents."""

from abc import ABC
from typing import Any
from uuid import UUID
from pydantic import BaseModel

from auto_pr.core.models import AgentPermissionScope
from auto_pr.llm.client import LLMClient, LLMResponse
from auto_pr.db.repository import WorkflowRepository


class AgentPermissionViolationError(Exception):
    """Raised when an agent attempts an action outside its permission scope."""


class AgentExecutionError(Exception):
    """Raised when an agent execution fails due to schema validation or model errors."""


class BaseAgent(ABC):
    """Base class for all specialized agents in the Auto PR Control Plane."""

    def __init__(
        self,
        name: str,
        permission_scope: AgentPermissionScope,
        llm_client: LLMClient,
        repository: WorkflowRepository | None = None,
    ) -> None:
        self.name = name
        self.permission_scope = permission_scope
        self.llm_client = llm_client
        self.repository = repository

    def check_tool_permission(self, tool_name: str) -> None:
        """Verify that the agent is explicitly allowed to invoke this tool."""
        if tool_name not in self.permission_scope.allowed_tools:
            raise AgentPermissionViolationError(
                f"Agent '{self.name}' is not authorized to invoke tool '{tool_name}'."
            )

    def check_write_permission(self) -> None:
        """Verify that the agent is authorized to write or modify code."""
        if not self.permission_scope.can_write_code:
            raise AgentPermissionViolationError(
                f"Agent '{self.name}' does not have permission to modify files."
            )

    def check_command_execution_permission(self) -> None:
        """Verify that the agent is authorized to execute commands."""
        if not self.permission_scope.can_execute_commands:
            raise AgentPermissionViolationError(
                f"Agent '{self.name}' does not have permission to execute commands."
            )

    async def record_execution(
        self,
        run_id: UUID | None,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        metadata: LLMResponse,
        status: str = "SUCCESS",
    ) -> None:
        """Record the agent turn in persistent storage with automated secret redaction."""
        if self.repository and run_id:
            await self.repository.record_agent_execution(
                run_id=run_id,
                agent_name=self.name,
                model_name=metadata.model_name,
                input_payload=input_payload,
                output_payload=output_payload,
                prompt_tokens=metadata.prompt_tokens,
                completion_tokens=metadata.completion_tokens,
                duration_ms=metadata.duration_ms,
                status=status,
            )
