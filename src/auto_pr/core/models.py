"""Core domain models for Auto PR Control Plane.

All domain contracts are strongly typed with Pydantic V2 models, ensuring
strict validation, least-privilege tool specifications, and evidence-first schemas.
"""

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, field_validator


# =====================================================================
# Least-Privilege Agent Permissions
# =====================================================================


class AgentPermissionScope(BaseModel):
    """Explicit least-privilege permissions assigned to an agent."""

    agent_name: str
    allowed_tools: set[str] = Field(default_factory=set)
    can_read_code: bool = False
    can_write_code: bool = False
    can_execute_commands: bool = False
    can_access_network: bool = False
    can_access_credentials: bool = False


# Predefined least-privilege scopes
UNDERSTANDING_AGENT_PERMISSIONS = AgentPermissionScope(
    agent_name="WorkItemUnderstandingAgent",
    allowed_tools=set(),
    can_read_code=False,
    can_write_code=False,
    can_execute_commands=False,
    can_access_network=False,
    can_access_credentials=False,
)

CONTEXT_COMPILER_PERMISSIONS = AgentPermissionScope(
    agent_name="ContextCompiler",
    allowed_tools={"search_code", "read_file_lines", "list_directory"},
    can_read_code=True,
    can_write_code=False,
    can_execute_commands=False,
    can_access_network=False,
    can_access_credentials=False,
)

IMPLEMENTATION_AGENT_PERMISSIONS = AgentPermissionScope(
    agent_name="ImplementationAgent",
    allowed_tools={
        "read_file_lines",
        "apply_file_patch",
        "create_file",
        "delete_file",
        "list_directory",
    },
    can_read_code=True,
    can_write_code=True,
    can_execute_commands=False,  # Commands are executed exclusively by ValidationEngine
    can_access_network=False,
    can_access_credentials=False,
)

DEBUGGING_AGENT_PERMISSIONS = AgentPermissionScope(
    agent_name="DebuggingAgent",
    allowed_tools=set(),  # Pure analytical reasoning over validation failure logs and diff
    can_read_code=True,
    can_write_code=False,
    can_execute_commands=False,
    can_access_network=False,
    can_access_credentials=False,
)

QUALITY_GATE_PERMISSIONS = AgentPermissionScope(
    agent_name="PRQualityAgent",
    allowed_tools=set(),  # Independent judge over evidence artifacts
    can_read_code=True,
    can_write_code=False,
    can_execute_commands=False,
    can_access_network=False,
    can_access_credentials=False,
)


# =====================================================================
# Work Item Input & Understanding Schemas
# =====================================================================


class WorkItemInput(BaseModel):
    """Raw input work item submitted by user or external ticket system."""

    external_id: str = Field(..., description="External ticket ID, e.g. ISSUE-42")
    source: Literal["MANUAL", "GITHUB_ISSUE", "JIRA", "LINEAR"] = "MANUAL"
    title: str = Field(..., min_length=3)
    raw_description: str = Field(..., min_length=5)
    repository_url: str = Field(..., description="Local repo path or remote git URL")
    base_branch: str = Field(default="main")


class AmbiguityChecklist(BaseModel):
    """Evidence-driven ambiguity detection checklist.

    Human escalation is triggered when concrete items fail, not merely
    from an arbitrary numeric threshold.
    """

    missing_expected_behavior: bool = Field(
        default=False,
        description="True if ticket fails to specify what the system should do",
    )
    unresolved_target_components: bool = Field(
        default=False,
        description="True if target area or file cannot be reasonably deduced",
    )
    contradictory_requirements: bool = Field(
        default=False,
        description="True if conflicting requirements exist in the issue description",
    )
    missing_verification_criteria: bool = Field(
        default=False,
        description="True if no clear verification criteria or acceptance test can be formulated",
    )
    unspecified_breaking_dependencies: bool = Field(
        default=False,
        description="True if breaking changes are required without explicit authorization",
    )
    findings: list[str] = Field(
        default_factory=list,
        description="Specific ambiguity reasons and missing information items",
    )

    def has_blockers(self) -> bool:
        """Returns True if any blocker in the checklist is raised."""
        return any(
            [
                self.missing_expected_behavior,
                self.unresolved_target_components,
                self.contradictory_requirements,
                self.missing_verification_criteria,
                self.unspecified_breaking_dependencies,
            ]
        )


class AcceptanceCriterion(BaseModel):
    """Individual acceptance criterion extracted from work item."""

    criterion_id: str
    description: str


class WorkItemSpec(BaseModel):
    """Structured understanding of work item produced by Understanding Agent."""

    problem_statement: str
    functional_requirements: list[str] = Field(min_length=1)
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1)
    technical_constraints: list[str] = Field(default_factory=list)
    ambiguity_checklist: AmbiguityChecklist = Field(default_factory=AmbiguityChecklist)
    ambiguity_detected: bool = Field(default=False)
    ambiguity_details: list[str] = Field(default_factory=list)
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Informational confidence metadata; escalation is governed by ambiguity_checklist",
    )

    @field_validator("acceptance_criteria", mode="before")
    @classmethod
    def normalize_acceptance_criteria(cls, v: Any) -> list[Any]:
        """Convert string list to list of AcceptanceCriterion objects if needed."""
        if isinstance(v, list):
            normalized = []
            for i, item in enumerate(v):
                if isinstance(item, str):
                    normalized.append(
                        AcceptanceCriterion(
                            criterion_id=f"AC-{i + 1}",
                            description=item,
                        )
                    )
                else:
                    normalized.append(item)
            return normalized
        return v

    def model_post_init(self, __context: Any) -> None:
        """Synchronize ambiguity fields between checklist and summary fields."""
        if self.ambiguity_checklist.has_blockers():
            object.__setattr__(self, "ambiguity_detected", True)
            if not self.ambiguity_details and self.ambiguity_checklist.findings:
                object.__setattr__(
                    self, "ambiguity_details", list(self.ambiguity_checklist.findings)
                )
        elif self.ambiguity_detected:
            # If flagged from LLM output, ensure checklist findings reflect it
            if self.ambiguity_details and not self.ambiguity_checklist.findings:
                self.ambiguity_checklist.findings.extend(self.ambiguity_details)
                self.ambiguity_checklist.missing_expected_behavior = True


# =====================================================================
# Context & Evidence Schemas
# =====================================================================


class FileExtract(BaseModel):
    """Ranked file extract with relevant line spans and symbol context."""

    file_path: str
    start_line: int = 1
    end_line: int = 1
    content: str
    relevance_score: float = Field(default=0.0, ge=0.0)
    symbol_name: str | None = None


class SymbolInfo(BaseModel):
    """Extracted language symbol metadata."""

    name: str
    kind: str = Field(..., description="'class', 'function', 'method', 'import', 'module'")
    file_path: str
    line_start: int = 1
    line_end: int = 1
    signature: str | None = None
    docstring: str | None = None


class ContextPack(BaseModel):
    """Compiled, ranked evidence pack fed to the Implementation Agent."""

    target_files: list[FileExtract] = Field(default_factory=list)
    relevant_symbols: list[SymbolInfo] = Field(default_factory=list)
    test_files: list[str] = Field(default_factory=list)
    build_command: str | None = None
    test_command: str = Field(default="pytest", description="Discovered or configured test command")
    lint_command: str | None = None
    typecheck_command: str | None = None
    detected_commands: dict[str, str | None] = Field(default_factory=dict)
    coding_standards: list[str] = Field(default_factory=list)
    evidence_sources: list[str] = Field(default_factory=list)
    ranking_details: dict[str, float] = Field(default_factory=dict)
    evidence_tokens_used: int = 0
    token_budget: int = 8000


# =====================================================================
# Implementation & ChangeSet Schemas
# =====================================================================


class FilePatch(BaseModel):
    """Specific file patch proposed by Implementation Agent."""

    file_path: str
    action: Literal["CREATE", "MODIFY", "DELETE"]
    content: str | None = None
    patch_diff: str | None = None


class ChangeSet(BaseModel):
    """Collection of file modifications ready for validation."""

    iteration: int = 1
    summary: str
    patches: list[FilePatch] = Field(min_length=1)
    commit_message: str


# =====================================================================
# Real Validation Schemas
# =====================================================================


class ValidationCommandResult(BaseModel):
    """Subprocess execution output from a real validation command."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    passed: bool

    @field_validator("passed", mode="before")
    @classmethod
    def check_passed(cls, v: Any, info: Any) -> bool:
        return v if isinstance(v, bool) else False


class ValidationRun(BaseModel):
    """Complete validation run aggregating all real execution outputs."""

    iteration: int = 1
    command_results: list[ValidationCommandResult] = Field(default_factory=list)
    all_passed: bool = False
    duration_ms: int = 0
    failure_summary: str | None = None


# =====================================================================
# Debugging & Failure Schemas
# =====================================================================


class DebugHypothesis(BaseModel):
    """Root cause diagnosis and remediation plan generated by Debugging Agent."""

    failure_type: Literal[
        "SYNTAX_ERROR",
        "ASSERTION_FAILURE",
        "IMPORT_ERROR",
        "TYPE_ERROR",
        "TIMEOUT",
        "ENVIRONMENT_ISSUE",
    ]
    failing_location: str = Field(..., description="file:line or function name")
    root_cause_explanation: str
    remediation_steps: list[str] = Field(min_length=1)


# =====================================================================
# Human Intervention Schemas
# =====================================================================


class HumanInterventionRequest(BaseModel):
    """Diagnostic package and escalation details presented to human."""

    run_id: UUID
    reason: Literal[
        "RETRIES_EXHAUSTED",
        "AMBIGUOUS_SPEC",
        "DANGEROUS_ACTION_DETECTED",
        "UNVERIFIABLE_VALIDATION",
    ]
    diagnostic_details: dict[str, Any]
    prompt_to_human: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HumanGuidance(BaseModel):
    """Guidance or decision provided by human supervisor."""

    decision: Literal["RESUME", "ABORT"]
    guidance_text: str = ""
    updated_requirements: list[str] = Field(default_factory=list)


# =====================================================================
# PR Quality Gate Schemas
# =====================================================================


class CriterionVerification(BaseModel):
    """Evidence verification for a single acceptance criterion."""

    criterion_id: str
    criterion_description: str
    satisfied: bool
    evidence_summary: str = Field(
        ...,
        description="Explicit proof of satisfaction (e.g. test assertion reference)",
    )


class DiffRiskAnalysis(BaseModel):
    """Diff risk and safety assessment."""

    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    unintended_files_modified: list[str] = Field(default_factory=list)
    breaking_changes_suspected: bool = False
    risk_factors: list[str] = Field(default_factory=list)


class QualityGateReport(BaseModel):
    """Evidence-based PR Quality evaluation.

    Must NOT approve PR solely based on an LLM numerical score.
    """

    criteria_evaluations: list[CriterionVerification]
    all_criteria_satisfied: bool
    validation_execution_passed: bool
    diff_risk: DiffRiskAnalysis
    repo_rules_followed: bool
    verdict: Literal["APPROVED", "REJECTED"]
    justification: str

    def is_approved(self) -> bool:
        """Strict evidence-based approval rule."""
        return (
            self.verdict == "APPROVED"
            and self.all_criteria_satisfied
            and self.validation_execution_passed
            and not self.diff_risk.unintended_files_modified
            and self.diff_risk.risk_level != "HIGH"
            and self.repo_rules_followed
        )


# =====================================================================
# PR Generation Schema
# =====================================================================


class PullRequestInfo(BaseModel):
    """Final Pull Request metadata and evidence-backed markdown body."""

    branch_name: str
    base_branch: str
    commit_sha: str
    title: str
    body_markdown: str
    pr_number: int | None = None
    pr_url: str | None = None
