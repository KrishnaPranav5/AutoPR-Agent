"""Unit tests for the Deterministic Finite State Machine engine."""

import pytest
from auto_pr.core.states import WorkflowState, DomainEvent
from auto_pr.core.fsm import (
    DeterministicFSM,
    InvalidStateTransitionError,
    GuardConditionFailedError,
)
from auto_pr.core.models import (
    WorkItemSpec,
    AmbiguityChecklist,
    AcceptanceCriterion,
    ValidationRun,
    ValidationCommandResult,
    QualityGateReport,
    CriterionVerification,
    DiffRiskAnalysis,
)


def create_sample_spec(ambiguous: bool = False) -> WorkItemSpec:
    """Helper to generate valid or ambiguous WorkItemSpec."""
    checklist = AmbiguityChecklist(
        missing_expected_behavior=ambiguous,
        findings=["Unclear requirements"] if ambiguous else [],
    )
    return WorkItemSpec(
        problem_statement="Add user rate limiter",
        functional_requirements=["Limit requests to 60/min"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="AC-1",
                description="429 Too Many Requests returned on 61st request",
            )
        ],
        ambiguity_checklist=checklist,
    )


def create_sample_validation_run(passed: bool = True) -> ValidationRun:
    """Helper to generate passing or failing ValidationRun."""
    cmd_res = ValidationCommandResult(
        command="pytest tests/",
        exit_code=0 if passed else 1,
        stdout="1 passed" if passed else "1 failed",
        stderr="",
        duration_ms=450,
        passed=passed,
    )
    return ValidationRun(
        iteration=1,
        command_results=[cmd_res],
        all_passed=passed,
        duration_ms=450,
    )


def create_sample_quality_report(approved: bool = True) -> QualityGateReport:
    """Helper to generate approved or rejected QualityGateReport."""
    criterion = CriterionVerification(
        criterion_id="AC-1",
        criterion_description="Rate limiting test asserts 429",
        satisfied=approved,
        evidence_summary="Test passed in tests/test_limiter.py line 30" if approved else "No tests found",
    )
    risk = DiffRiskAnalysis(
        risk_level="LOW" if approved else "HIGH",
        unintended_files_modified=[] if approved else ["secrets.env"],
        breaking_changes_suspected=not approved,
    )
    return QualityGateReport(
        criteria_evaluations=[criterion],
        all_criteria_satisfied=approved,
        validation_execution_passed=approved,
        diff_risk=risk,
        repo_rules_followed=approved,
        verdict="APPROVED" if approved else "REJECTED",
        justification="Verified against test evidence" if approved else "Failed checks",
    )


def test_canonical_happy_path_transitions() -> None:
    """Verify that the full happy-path workflow executes through each state in sequence."""
    fsm = DeterministicFSM()
    state = WorkflowState.SUBMITTED

    # SUBMITTED -> UNDERSTANDING
    state = fsm.transition(state, DomainEvent.START_RUN)
    assert state == WorkflowState.UNDERSTANDING

    # UNDERSTANDING -> CONTEXT_DISCOVERING
    spec = create_sample_spec(ambiguous=False)
    state = fsm.transition(state, DomainEvent.SPEC_READY, {"spec": spec})
    assert state == WorkflowState.CONTEXT_DISCOVERING

    # CONTEXT_DISCOVERING -> CONTEXT_COMPILING
    state = fsm.transition(state, DomainEvent.DISCOVERY_DONE)
    assert state == WorkflowState.CONTEXT_COMPILING

    # CONTEXT_COMPILING -> IMPLEMENTING
    state = fsm.transition(state, DomainEvent.EVIDENCE_PACKED)
    assert state == WorkflowState.IMPLEMENTING

    # IMPLEMENTING -> VALIDATING
    state = fsm.transition(state, DomainEvent.CHANGESET_READY)
    assert state == WorkflowState.VALIDATING

    # VALIDATING -> VALIDATION_GATE
    state = fsm.transition(state, DomainEvent.VALIDATION_DONE)
    assert state == WorkflowState.VALIDATION_GATE

    # VALIDATION_GATE -> PR_QUALITY_GATE
    val_run = create_sample_validation_run(passed=True)
    state = fsm.transition(state, DomainEvent.GATE_PASS, {"validation_run": val_run})
    assert state == WorkflowState.PR_QUALITY_GATE

    # PR_QUALITY_GATE -> PR_GENERATING
    report = create_sample_quality_report(approved=True)
    state = fsm.transition(state, DomainEvent.QUALITY_PASS, {"quality_report": report})
    assert state == WorkflowState.PR_GENERATING

    # PR_GENERATING -> NOTIFYING
    state = fsm.transition(state, DomainEvent.PR_CREATED)
    assert state == WorkflowState.NOTIFYING

    # NOTIFYING -> COMPLETED
    state = fsm.transition(state, DomainEvent.NOTIFICATIONS_SENT)
    assert state == WorkflowState.COMPLETED


def test_rejects_arbitrary_or_illegal_transitions() -> None:
    """Verify that illegal transitions raise InvalidStateTransitionError."""
    fsm = DeterministicFSM()

    # Cannot jump from SUBMITTED directly to PR_GENERATING or COMPLETED
    with pytest.raises(InvalidStateTransitionError):
        fsm.transition(WorkflowState.SUBMITTED, DomainEvent.PR_CREATED)

    with pytest.raises(InvalidStateTransitionError):
        fsm.transition(WorkflowState.SUBMITTED, DomainEvent.GATE_PASS)

    # Terminal state cannot accept transitions
    with pytest.raises(InvalidStateTransitionError):
        fsm.transition(WorkflowState.COMPLETED, DomainEvent.START_RUN)


def test_guard_blocks_spec_ready_when_ambiguity_blockers_exist() -> None:
    """Verify that SPEC_READY is blocked when ambiguity checklist has blockers."""
    fsm = DeterministicFSM()
    state = WorkflowState.UNDERSTANDING
    ambiguous_spec = create_sample_spec(ambiguous=True)

    with pytest.raises(GuardConditionFailedError) as exc_info:
        fsm.transition(state, DomainEvent.SPEC_READY, {"spec": ambiguous_spec})

    assert "blocking ambiguities" in str(exc_info.value)

    # Escalation path is valid
    escalated_state = fsm.transition(state, DomainEvent.AMBIGUITY_ESCALATE)
    assert escalated_state == WorkflowState.HUMAN_ESCALATION


def test_guard_blocks_validation_gate_pass_on_test_failure() -> None:
    """Verify that Validation Gate cannot be passed if test execution failed."""
    fsm = DeterministicFSM()
    state = WorkflowState.VALIDATION_GATE
    failed_val_run = create_sample_validation_run(passed=False)

    # Cannot GATE_PASS with failing execution
    with pytest.raises(GuardConditionFailedError) as exc_info:
        fsm.transition(state, DomainEvent.GATE_PASS, {"validation_run": failed_val_run})
    assert "real test execution reported failures" in str(exc_info.value)

    # GATE_FAIL_RETRY works if retries are available
    retry_state = fsm.transition(
        state,
        DomainEvent.GATE_FAIL_RETRY,
        {"validation_run": failed_val_run, "retry_count": 1, "max_retries": 3},
    )
    assert retry_state == WorkflowState.DEBUGGING


def test_guard_enforces_retry_limit_at_validation_gate() -> None:
    """Verify that GATE_FAIL_RETRY is blocked and GATE_FAIL_LIMIT required when budget is exhausted."""
    fsm = DeterministicFSM()
    state = WorkflowState.VALIDATION_GATE
    failed_val_run = create_sample_validation_run(passed=False)

    # Attempting retry when count == max_retries must fail
    with pytest.raises(GuardConditionFailedError) as exc_info:
        fsm.transition(
            state,
            DomainEvent.GATE_FAIL_RETRY,
            {"validation_run": failed_val_run, "retry_count": 3, "max_retries": 3},
        )
    assert "Retry limit" in str(exc_info.value)

    # Transitioning to HUMAN_ESCALATION via GATE_FAIL_LIMIT succeeds
    escalated_state = fsm.transition(
        state,
        DomainEvent.GATE_FAIL_LIMIT,
        {"validation_run": failed_val_run, "retry_count": 3, "max_retries": 3},
    )
    assert escalated_state == WorkflowState.HUMAN_ESCALATION


def test_guard_blocks_pr_quality_gate_without_valid_evidence() -> None:
    """Verify that PR Quality Gate strictly rejects non-approved quality reports."""
    fsm = DeterministicFSM()
    state = WorkflowState.PR_QUALITY_GATE
    unapproved_report = create_sample_quality_report(approved=False)

    with pytest.raises(GuardConditionFailedError) as exc_info:
        fsm.transition(state, DomainEvent.QUALITY_PASS, {"quality_report": unapproved_report})
    assert "PR Quality Gate cannot be approved" in str(exc_info.value)
