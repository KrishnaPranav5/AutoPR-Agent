"""Unit tests for domain models, permission scopes, and evidence validation."""

from auto_pr.core.models import (
    UNDERSTANDING_AGENT_PERMISSIONS,
    IMPLEMENTATION_AGENT_PERMISSIONS,
    DEBUGGING_AGENT_PERMISSIONS,
    QUALITY_GATE_PERMISSIONS,
    AmbiguityChecklist,
    QualityGateReport,
    CriterionVerification,
    DiffRiskAnalysis,
    WorkItemInput,
)


def test_agent_least_privilege_permissions() -> None:
    """Verify that agents only have permissions strictly necessary for their role."""
    # Understanding Agent cannot write, execute, or access credentials
    assert not UNDERSTANDING_AGENT_PERMISSIONS.can_write_code
    assert not UNDERSTANDING_AGENT_PERMISSIONS.can_execute_commands
    assert not UNDERSTANDING_AGENT_PERMISSIONS.can_access_credentials
    assert len(UNDERSTANDING_AGENT_PERMISSIONS.allowed_tools) == 0

    # Implementation Agent can write code but cannot execute arbitrary commands
    assert IMPLEMENTATION_AGENT_PERMISSIONS.can_write_code
    assert not IMPLEMENTATION_AGENT_PERMISSIONS.can_execute_commands
    assert not IMPLEMENTATION_AGENT_PERMISSIONS.can_access_credentials
    assert "apply_file_patch" in IMPLEMENTATION_AGENT_PERMISSIONS.allowed_tools

    # Debugging Agent cannot write code or execute commands
    assert not DEBUGGING_AGENT_PERMISSIONS.can_write_code
    assert not DEBUGGING_AGENT_PERMISSIONS.can_execute_commands

    # Quality Gate Agent is an independent judge
    assert not QUALITY_GATE_PERMISSIONS.can_write_code
    assert not QUALITY_GATE_PERMISSIONS.can_execute_commands


def test_ambiguity_checklist_blocker_detection() -> None:
    """Verify that AmbiguityChecklist flags blockers appropriately."""
    clean_checklist = AmbiguityChecklist()
    assert not clean_checklist.has_blockers()

    blocked_checklist = AmbiguityChecklist(
        contradictory_requirements=True,
        findings=["Requirement 1 conflicts with Requirement 2"],
    )
    assert blocked_checklist.has_blockers()


def test_quality_gate_evidence_based_approval() -> None:
    """Verify that QualityGateReport is_approved() requires all evidence criteria."""
    valid_criterion = CriterionVerification(
        criterion_id="CR-1",
        criterion_description="Rate limiting functional",
        satisfied=True,
        evidence_summary="Verified by test_limiter.py:20",
    )
    low_risk = DiffRiskAnalysis(
        risk_level="LOW",
        unintended_files_modified=[],
        breaking_changes_suspected=False,
    )

    # Approved case
    report = QualityGateReport(
        criteria_evaluations=[valid_criterion],
        all_criteria_satisfied=True,
        validation_execution_passed=True,
        diff_risk=low_risk,
        repo_rules_followed=True,
        verdict="APPROVED",
        justification="All evidence verified",
    )
    assert report.is_approved()

    # Rejected if unintended files were modified, even if verdict was set to APPROVED
    bad_diff_report = report.model_copy(
        update={
            "diff_risk": DiffRiskAnalysis(
                risk_level="HIGH",
                unintended_files_modified=["config/database.yml"],
                breaking_changes_suspected=True,
            )
        }
    )
    assert not bad_diff_report.is_approved()

    # Rejected if validation execution did not pass
    unverified_report = report.model_copy(update={"validation_execution_passed": False})
    assert not unverified_report.is_approved()
