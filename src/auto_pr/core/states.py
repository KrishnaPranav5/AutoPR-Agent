"""Workflow states and deterministic transition definitions."""

from enum import Enum


class WorkflowState(str, Enum):
    """Authoritative workflow states for the Auto PR Control Plane."""

    SUBMITTED = "SUBMITTED"
    UNDERSTANDING = "UNDERSTANDING"
    CONTEXT_DISCOVERING = "CONTEXT_DISCOVERING"
    CONTEXT_COMPILING = "CONTEXT_COMPILING"
    IMPLEMENTING = "IMPLEMENTING"
    VALIDATING = "VALIDATING"
    VALIDATION_GATE = "VALIDATION_GATE"
    DEBUGGING = "DEBUGGING"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"
    PR_QUALITY_GATE = "PR_QUALITY_GATE"
    PR_GENERATING = "PR_GENERATING"
    NOTIFYING = "NOTIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class DomainEvent(str, Enum):
    """Authoritative domain events triggering state transitions."""

    START_RUN = "START_RUN"
    SPEC_READY = "SPEC_READY"
    AMBIGUITY_ESCALATE = "AMBIGUITY_ESCALATE"
    DISCOVERY_DONE = "DISCOVERY_DONE"
    EVIDENCE_PACKED = "EVIDENCE_PACKED"
    CHANGESET_READY = "CHANGESET_READY"
    VALIDATION_DONE = "VALIDATION_DONE"
    GATE_PASS = "GATE_PASS"
    GATE_FAIL_RETRY = "GATE_FAIL_RETRY"
    GATE_FAIL_LIMIT = "GATE_FAIL_LIMIT"
    HYPOTHESIS_READY = "HYPOTHESIS_READY"
    QUALITY_PASS = "QUALITY_PASS"
    QUALITY_FAIL_RETRY = "QUALITY_FAIL_RETRY"
    QUALITY_FAIL_LIMIT = "QUALITY_FAIL_LIMIT"
    PR_CREATED = "PR_CREATED"
    NOTIFICATIONS_SENT = "NOTIFICATIONS_SENT"
    HUMAN_RESUME = "HUMAN_RESUME"
    HUMAN_ABORT = "HUMAN_ABORT"
    FATAL_ERROR = "FATAL_ERROR"


# Strict deterministic state transition table: (CurrentState, DomainEvent) -> NextState
VALID_TRANSITIONS: dict[tuple[WorkflowState, DomainEvent], WorkflowState] = {
    (WorkflowState.SUBMITTED, DomainEvent.START_RUN): WorkflowState.UNDERSTANDING,
    (WorkflowState.UNDERSTANDING, DomainEvent.SPEC_READY): WorkflowState.CONTEXT_DISCOVERING,
    (WorkflowState.UNDERSTANDING, DomainEvent.AMBIGUITY_ESCALATE): WorkflowState.HUMAN_ESCALATION,
    (WorkflowState.CONTEXT_DISCOVERING, DomainEvent.DISCOVERY_DONE): WorkflowState.CONTEXT_COMPILING,
    (WorkflowState.CONTEXT_COMPILING, DomainEvent.EVIDENCE_PACKED): WorkflowState.IMPLEMENTING,
    (WorkflowState.IMPLEMENTING, DomainEvent.CHANGESET_READY): WorkflowState.VALIDATING,
    (WorkflowState.VALIDATING, DomainEvent.VALIDATION_DONE): WorkflowState.VALIDATION_GATE,
    (WorkflowState.VALIDATION_GATE, DomainEvent.GATE_PASS): WorkflowState.PR_QUALITY_GATE,
    (WorkflowState.VALIDATION_GATE, DomainEvent.GATE_FAIL_RETRY): WorkflowState.DEBUGGING,
    (WorkflowState.VALIDATION_GATE, DomainEvent.GATE_FAIL_LIMIT): WorkflowState.HUMAN_ESCALATION,
    (WorkflowState.DEBUGGING, DomainEvent.HYPOTHESIS_READY): WorkflowState.IMPLEMENTING,
    (WorkflowState.PR_QUALITY_GATE, DomainEvent.QUALITY_PASS): WorkflowState.PR_GENERATING,
    (WorkflowState.PR_QUALITY_GATE, DomainEvent.QUALITY_FAIL_RETRY): WorkflowState.DEBUGGING,
    (WorkflowState.PR_QUALITY_GATE, DomainEvent.QUALITY_FAIL_LIMIT): WorkflowState.HUMAN_ESCALATION,
    (WorkflowState.PR_GENERATING, DomainEvent.PR_CREATED): WorkflowState.NOTIFYING,
    (WorkflowState.NOTIFYING, DomainEvent.NOTIFICATIONS_SENT): WorkflowState.COMPLETED,
    (WorkflowState.HUMAN_ESCALATION, DomainEvent.HUMAN_RESUME): WorkflowState.IMPLEMENTING,
    (WorkflowState.HUMAN_ESCALATION, DomainEvent.HUMAN_ABORT): WorkflowState.FAILED,
}

# Terminal states where no further automatic transitions are permitted
TERMINAL_STATES = frozenset([WorkflowState.COMPLETED, WorkflowState.FAILED])
