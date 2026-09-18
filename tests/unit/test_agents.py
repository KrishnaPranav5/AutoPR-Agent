"""Unit tests for WorkItemUnderstandingAgent, permission boundaries, and persistence."""

import pytest
from auto_pr.core.models import (
    WorkItemInput,
    WorkItemSpec,
    AcceptanceCriterion,
    AmbiguityChecklist,
)
from auto_pr.llm.mock import MockLLMClient
from auto_pr.agents.understanding import WorkItemUnderstandingAgent
from auto_pr.agents.base import AgentPermissionViolationError, AgentExecutionError
from auto_pr.db.repository import WorkflowRepository


@pytest.fixture
def sample_work_item() -> WorkItemInput:
    return WorkItemInput(
        external_id="FEAT-200",
        source="MANUAL",
        title="Add health check endpoint",
        raw_description="Add a GET /healthz endpoint returning 200 OK and status pass.",
        repository_url="https://github.com/example/api-repo",
        base_branch="main",
    )


@pytest.mark.asyncio
async def test_understanding_agent_valid_structured_response(
    sample_work_item: WorkItemInput,
) -> None:
    """Verify understanding agent correctly parses structured output into WorkItemSpec."""
    mock_llm = MockLLMClient()
    mock_llm.queue_structured_response(
        {
            "problem_statement": "System lacks an automated health check endpoint",
            "functional_requirements": ["Respond with 200 OK on GET /healthz"],
            "acceptance_criteria": ["GET /healthz returns status code 200"],
            "technical_constraints": ["Use FastAPI router"],
            "ambiguity_detected": False,
            "ambiguity_details": [],
            "confidence_score": 0.95,
        }
    )

    agent = WorkItemUnderstandingAgent(llm_client=mock_llm)
    spec = await agent.analyze(sample_work_item)

    assert isinstance(spec, WorkItemSpec)
    assert spec.problem_statement == "System lacks an automated health check endpoint"
    assert len(spec.acceptance_criteria) == 1
    assert spec.acceptance_criteria[0].criterion_id == "AC-1"
    assert not spec.ambiguity_detected
    assert not spec.ambiguity_checklist.has_blockers()
    assert spec.confidence_score == 0.95


@pytest.mark.asyncio
async def test_understanding_agent_malformed_response_rejection(
    sample_work_item: WorkItemInput,
) -> None:
    """Verify that malformed model outputs are rejected with AgentExecutionError."""
    mock_llm = MockLLMClient()
    mock_llm.queue_structured_response("MALFORMED_OUTPUT_NOT_JSON")

    agent = WorkItemUnderstandingAgent(llm_client=mock_llm)
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.analyze(sample_work_item)

    assert "failed schema validation" in str(exc_info.value)


@pytest.mark.asyncio
async def test_understanding_agent_missing_required_fields(
    sample_work_item: WorkItemInput,
) -> None:
    """Verify that model output missing required fields is rejected."""
    mock_llm = MockLLMClient()
    # Missing functional_requirements and acceptance_criteria
    mock_llm.queue_structured_response(
        {
            "problem_statement": "Only problem statement given",
            "functional_requirements": [],  # requires min_length=1
            "acceptance_criteria": [],      # requires min_length=1
        }
    )

    agent = WorkItemUnderstandingAgent(llm_client=mock_llm)
    with pytest.raises(AgentExecutionError) as exc_info:
        await agent.analyze(sample_work_item)

    assert "failed schema validation" in str(exc_info.value)


@pytest.mark.asyncio
async def test_understanding_agent_ambiguity_blocker_detection(
    sample_work_item: WorkItemInput,
) -> None:
    """Verify that ambiguity blockers in the checklist are detected and surfaced."""
    mock_llm = MockLLMClient()
    mock_llm.queue_structured_response(
        {
            "problem_statement": "Vague request to fix database",
            "functional_requirements": ["Fix the database error"],
            "acceptance_criteria": ["Database works"],
            "ambiguity_checklist": {
                "missing_expected_behavior": True,
                "findings": ["No expected schema or error traceback specified"],
            },
            "ambiguity_detected": True,
            "ambiguity_details": ["No expected schema or error traceback specified"],
            "confidence_score": 0.5,
        }
    )

    agent = WorkItemUnderstandingAgent(llm_client=mock_llm)
    spec = await agent.analyze(sample_work_item)

    assert spec.ambiguity_detected
    assert spec.ambiguity_checklist.has_blockers()
    assert spec.ambiguity_checklist.missing_expected_behavior
    assert "No expected schema" in spec.ambiguity_checklist.findings[0]


@pytest.mark.asyncio
async def test_understanding_agent_contradictory_requirements(
    sample_work_item: WorkItemInput,
) -> None:
    """Verify that contradictory requirements are flagged as blockers."""
    mock_llm = MockLLMClient()
    mock_llm.queue_structured_response(
        {
            "problem_statement": "Conflicting timeout parameters",
            "functional_requirements": ["Set timeout to 10s", "Set timeout to 0s"],
            "acceptance_criteria": ["Timeout behaves consistently"],
            "ambiguity_checklist": {
                "contradictory_requirements": True,
                "findings": ["Timeout specified as both 10s and 0s"],
            },
            "ambiguity_detected": True,
            "ambiguity_details": ["Timeout specified as both 10s and 0s"],
            "confidence_score": 0.6,
        }
    )

    agent = WorkItemUnderstandingAgent(llm_client=mock_llm)
    spec = await agent.analyze(sample_work_item)

    assert spec.ambiguity_detected
    assert spec.ambiguity_checklist.contradictory_requirements
    assert spec.ambiguity_checklist.has_blockers()


@pytest.mark.asyncio
async def test_understanding_agent_non_blocking_low_confidence(
    sample_work_item: WorkItemInput,
) -> None:
    """Verify that low confidence alone does NOT flag ambiguity blockers if checklist is clean."""
    mock_llm = MockLLMClient()
    mock_llm.queue_structured_response(
        {
            "problem_statement": "Implement standard utility function",
            "functional_requirements": ["Add slugify string utility"],
            "acceptance_criteria": ["Converts 'Hello World' to 'hello-world'"],
            "ambiguity_checklist": {
                "missing_expected_behavior": False,
                "unresolved_target_components": False,
                "contradictory_requirements": False,
                "missing_verification_criteria": False,
                "unspecified_breaking_dependencies": False,
                "findings": [],
            },
            "ambiguity_detected": False,
            "ambiguity_details": [],
            "confidence_score": 0.45,  # Low confidence metadata
        }
    )

    agent = WorkItemUnderstandingAgent(llm_client=mock_llm)
    spec = await agent.analyze(sample_work_item)

    # Must NOT have blockers simply due to low confidence score
    assert not spec.ambiguity_checklist.has_blockers()
    assert not spec.ambiguity_detected
    assert spec.confidence_score == 0.45


def test_understanding_agent_permission_boundaries() -> None:
    """Verify that the understanding agent cannot invoke tools or modify code."""
    mock_llm = MockLLMClient()
    agent = WorkItemUnderstandingAgent(llm_client=mock_llm)

    # Must reject unauthorized tool invocation
    with pytest.raises(AgentPermissionViolationError):
        agent.check_tool_permission("apply_file_patch")

    # Must reject unauthorized write permissions
    with pytest.raises(AgentPermissionViolationError):
        agent.check_write_permission()

    # Must reject unauthorized command execution
    with pytest.raises(AgentPermissionViolationError):
        agent.check_command_execution_permission()


@pytest.mark.asyncio
async def test_understanding_agent_audit_persistence_and_redaction(
    sample_work_item: WorkItemInput,
    repo: WorkflowRepository,
) -> None:
    """Verify agent execution is persisted and sensitive tokens are redacted in storage."""
    # Create work item and run in repo
    db_work_item = await repo.create_work_item(sample_work_item)
    run = await repo.create_run(work_item_id=db_work_item.id)

    mock_llm = MockLLMClient()
    # Mock response containing a sensitive token in technical_constraints
    mock_llm.queue_structured_response(
        {
            "problem_statement": "Secure API endpoint",
            "functional_requirements": ["Add token auth"],
            "acceptance_criteria": ["Tokens validated properly"],
            "technical_constraints": [
                "Use token ghp_1234567890abcdefghijklmnopqrstuvwxyz12 for service auth"
            ],
            "ambiguity_detected": False,
            "ambiguity_details": [],
            "confidence_score": 0.99,
        }
    )

    # Add sensitive token to description to test input redaction
    work_item_with_secret = sample_work_item.model_copy(
        update={
            "raw_description": "Config with secret password super_secret_123 and token ghp_9999999999abcdefghijklmnopqrstuvwxyz99"
        }
    )

    agent = WorkItemUnderstandingAgent(llm_client=mock_llm, repository=repo)
    spec = await agent.analyze(work_item_with_secret, run_id=run.id)
    assert spec is not None

    # Verify run record in database has preloaded agent execution
    loaded_run = await repo.get_run(run.id)
    assert loaded_run is not None
    assert len(loaded_run.agent_executions) == 1

    exec_record = loaded_run.agent_executions[0]
    assert exec_record.agent_name == "WorkItemUnderstandingAgent"
    assert exec_record.status == "SUCCESS"

    # Verify input secret redaction in database
    input_str = str(exec_record.input_payload)
    assert "ghp_9999999999abcdefghijklmnopqrstuvwxyz99" not in input_str
    assert "[REDACTED_GITHUB_TOKEN]" in input_str

    # Verify output secret redaction in database
    output_str = str(exec_record.output_payload)
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz12" not in output_str
    assert "[REDACTED_GITHUB_TOKEN]" in output_str
