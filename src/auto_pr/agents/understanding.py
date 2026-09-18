"""Work Item Understanding Agent.

Deconstructs raw ticket descriptions and requirements into structured,
evidence-driven WorkItemSpecs, identifying functional requirements,
acceptance criteria, and concrete ambiguity blockers.
"""

from typing import Any
from uuid import UUID

from auto_pr.core.models import (
    WorkItemInput,
    WorkItemSpec,
    UNDERSTANDING_AGENT_PERMISSIONS,
)
from auto_pr.llm.client import LLMClient, LLMStructuredOutputError, LLMClientError
from auto_pr.db.repository import WorkflowRepository
from auto_pr.agents.base import BaseAgent, AgentExecutionError

SYSTEM_INSTRUCTION = """You are the Work Item Understanding Agent for the Auto PR Control Plane.
Your task is to analyze software work items (bug reports, feature requests, or tasks) and produce a structured, unambiguous specification.

You must rigorously evaluate:
1. The core problem statement.
2. Concrete functional requirements.
3. Testable acceptance criteria.
4. Technical constraints and considerations.
5. An evidence-based ambiguity checklist:
   - Check if expected behavior is missing.
   - Check if target components or files cannot be reasonably deduced.
   - Check if contradictory requirements exist.
   - Check if verification criteria are missing.
   - Check if unspecified breaking dependencies are required.
   If any of these conditions are true, raise the corresponding flag and document exact findings.

Output must strictly conform to the requested JSON schema. Do not include markdown code fences in output.
"""


class WorkItemUnderstandingAgent(BaseAgent):
    """Specialized agent responsible for interpreting work items and detecting ambiguities."""

    def __init__(
        self,
        llm_client: LLMClient,
        repository: WorkflowRepository | None = None,
    ) -> None:
        super().__init__(
            name="WorkItemUnderstandingAgent",
            permission_scope=UNDERSTANDING_AGENT_PERMISSIONS,
            llm_client=llm_client,
            repository=repository,
        )

    def _build_prompt(self, work_item: WorkItemInput, repo_rules: list[str] | None = None) -> str:
        """Construct prompt for the LLM."""
        prompt_parts = [
            f"# WORK ITEM: {work_item.external_id} - {work_item.title}",
            "",
            "## Description:",
            work_item.raw_description,
            "",
            f"## Repository Target:",
            f"URL/Path: {work_item.repository_url}",
            f"Base Branch: {work_item.base_branch}",
        ]

        if repo_rules:
            prompt_parts.extend(["", "## Repository Rules & Conventions:"])
            for rule in repo_rules:
                prompt_parts.append(f"- {rule}")

        prompt_parts.extend(
            [
                "",
                "Analyze this work item and output a structured WorkItemSpec.",
                "Ensure all functional requirements and acceptance criteria are concrete and testable.",
                "Thoroughly inspect the ambiguity checklist.",
            ]
        )
        return "\n".join(prompt_parts)

    async def analyze(
        self,
        work_item: WorkItemInput,
        repo_rules: list[str] | None = None,
        run_id: UUID | None = None,
    ) -> WorkItemSpec:
        """Analyze a work item and return a Pydantic-validated WorkItemSpec.

        Raises:
            AgentExecutionError: If LLM output fails schema validation or model error occurs.
        """
        prompt = self._build_prompt(work_item, repo_rules)
        input_payload: dict[str, Any] = {
            "external_id": work_item.external_id,
            "title": work_item.title,
            "raw_description": work_item.raw_description,
            "repo_rules": repo_rules or [],
        }

        try:
            spec, metadata = await self.llm_client.generate_structured(
                prompt=prompt,
                response_model=WorkItemSpec,
                system_instruction=SYSTEM_INSTRUCTION,
            )

            # Persist execution audit record
            await self.record_execution(
                run_id=run_id,
                input_payload=input_payload,
                output_payload=spec.model_dump(),
                metadata=metadata,
                status="SUCCESS",
            )
            return spec

        except LLMStructuredOutputError as err:
            # Failed schema validation
            if self.repository and run_id:
                await self.repository.record_agent_execution(
                    run_id=run_id,
                    agent_name=self.name,
                    model_name="unknown",
                    input_payload=input_payload,
                    output_payload={"error": str(err)},
                    prompt_tokens=0,
                    completion_tokens=0,
                    duration_ms=0,
                    status="SCHEMA_VALIDATION_FAILED",
                )
            raise AgentExecutionError(
                f"WorkItemUnderstandingAgent failed schema validation: {err}"
            ) from err

        except LLMClientError as err:
            if self.repository and run_id:
                await self.repository.record_agent_execution(
                    run_id=run_id,
                    agent_name=self.name,
                    model_name="unknown",
                    input_payload=input_payload,
                    output_payload={"error": str(err)},
                    prompt_tokens=0,
                    completion_tokens=0,
                    duration_ms=0,
                    status="PROVIDER_ERROR",
                )
            raise AgentExecutionError(
                f"WorkItemUnderstandingAgent encountered provider error: {err}"
            ) from err
