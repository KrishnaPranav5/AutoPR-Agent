"""Unit tests for database persistence, relationships, and audit trail."""

import pytest
from auto_pr.core.states import WorkflowState, DomainEvent
from auto_pr.core.models import (
    WorkItemInput,
    ChangeSet,
    FilePatch,
    ValidationRun,
    ValidationCommandResult,
    QualityGateReport,
    CriterionVerification,
    DiffRiskAnalysis,
    PullRequestInfo,
)
from auto_pr.db.repository import WorkflowRepository


@pytest.mark.asyncio
async def test_full_repository_lifecycle(repo: WorkflowRepository) -> None:
    """Verify end-to-end database operations, relations, and audit trail."""
    # 1. Create Work Item
    work_item_input = WorkItemInput(
        external_id="PR-101",
        source="MANUAL",
        title="Implement OAuth2 Token Refresh",
        raw_description="Add automatic token refresh logic to avoid expiry errors.",
        repository_url="https://github.com/example/demo-repo",
        base_branch="main",
    )
    work_item = await repo.create_work_item(work_item_input)
    assert work_item.id is not None
    assert work_item.external_id == "PR-101"

    # 2. Create Run
    run = await repo.create_run(work_item_id=work_item.id, max_retries=3)
    assert run.id is not None
    assert run.current_state == WorkflowState.SUBMITTED.value

    # 3. Transition Run State
    await repo.update_run_state(
        run_id=run.id,
        from_state=WorkflowState.SUBMITTED,
        to_state=WorkflowState.UNDERSTANDING,
        event=DomainEvent.START_RUN,
        details={"trigger": "user_cli"},
    )

    # 4. Record Agent Execution with sensitive token (verifying automatic secret redaction)
    agent_record = await repo.record_agent_execution(
        run_id=run.id,
        agent_name="WorkItemUnderstandingAgent",
        model_name="gemini-2.5-flash",
        input_payload={"prompt": "Analyze issue", "api_token": "ghp_secrettoken123456789012345678901234567"},
        output_payload={"spec": "valid spec", "env_secret": "Bearer supersecretjwttokenvalue12345"},
        prompt_tokens=150,
        completion_tokens=80,
        duration_ms=520,
    )
    assert agent_record.id is not None
    # Verify redactions in stored record
    assert agent_record.input_payload["api_token"] == "[REDACTED_SENSITIVE_VALUE]"
    assert "supersecretjwttokenvalue12345" not in str(agent_record.output_payload)

    # 5. Record ChangeSet
    changeset = ChangeSet(
        iteration=1,
        summary="Added token refresh method",
        patches=[
            FilePatch(
                file_path="src/auth.py",
                action="MODIFY",
                content="def refresh_token(): pass",
            )
        ],
        commit_message="feat(auth): add token refresh logic",
    )
    cs_record = await repo.record_change_set(run.id, changeset)
    assert cs_record.id is not None
    assert cs_record.commit_message == "feat(auth): add token refresh logic"

    # 6. Record Validation Run
    val_run = ValidationRun(
        iteration=1,
        command_results=[
            ValidationCommandResult(
                command="pytest tests/test_auth.py",
                exit_code=0,
                stdout="1 passed in 0.05s",
                stderr="",
                duration_ms=50,
                passed=True,
            )
        ],
        all_passed=True,
        duration_ms=50,
    )
    val_record = await repo.record_validation_run(run.id, val_run)
    assert val_record.all_passed is True

    # 7. Record Quality Gate
    report = QualityGateReport(
        criteria_evaluations=[
            CriterionVerification(
                criterion_id="AC-1",
                criterion_description="Token refresh",
                satisfied=True,
                evidence_summary="Verified in tests/test_auth.py",
            )
        ],
        all_criteria_satisfied=True,
        validation_execution_passed=True,
        diff_risk=DiffRiskAnalysis(risk_level="LOW"),
        repo_rules_followed=True,
        verdict="APPROVED",
        justification="All evidence verified",
    )
    qg_record = await repo.record_quality_gate(run.id, report)
    assert qg_record.verdict == "APPROVED"

    # 8. Record Pull Request
    pr_info = PullRequestInfo(
        branch_name="auto-pr/pr-101",
        base_branch="main",
        commit_sha="a1b2c3d4e5f6",
        title="feat(auth): add token refresh",
        body_markdown="## Changes\n- Added refresh\n## Evidence\n- pytest passed",
        pr_number=42,
        pr_url="https://github.com/example/demo-repo/pull/42",
    )
    pr_record = await repo.record_pull_request(run.id, pr_info)
    assert pr_record.pr_number == 42

    # 9. Verify Run retrieval with loaded relationships
    retrieved_run = await repo.get_run(run.id)
    assert retrieved_run is not None
    assert len(retrieved_run.state_history) == 2  # CREATE_RUN and START_RUN
    assert len(retrieved_run.agent_executions) == 1
    assert len(retrieved_run.change_sets) == 1
    assert len(retrieved_run.validation_runs) == 1
    assert len(retrieved_run.quality_gate_results) == 1
    assert retrieved_run.pull_request is not None
    assert retrieved_run.pull_request.pr_number == 42

    # 10. Verify Chronological Audit Trail
    audit_events = await repo.get_audit_trail(run.id)
    assert len(audit_events) >= 6
    event_names = [e.event_name for e in audit_events]
    assert "RUN_CREATED" in event_names
    assert "STATE_TRANSITION_START_RUN" in event_names
    assert "AGENT_EXECUTED" in event_names
    assert "VALIDATION_RUN_RECORDED" in event_names
    assert "QUALITY_GATE_EVALUATED" in event_names
    assert "PULL_REQUEST_RECORDED" in event_names
