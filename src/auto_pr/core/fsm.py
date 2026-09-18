"""Deterministic Finite State Machine (FSM) Engine.

Enforces authoritative workflow transitions with strict guard conditions.
LLM output NEVER directly sets or transitions state; only verified domain
events passing programmatic guards may transition the state machine.
"""

import logging
from typing import Any, Callable
from auto_pr.core.states import (
    WorkflowState,
    DomainEvent,
    VALID_TRANSITIONS,
    TERMINAL_STATES,
)
from auto_pr.core.models import WorkItemSpec, ValidationRun, QualityGateReport

logger = logging.getLogger(__name__)


class StateMachineError(Exception):
    """Base exception for state machine violations."""


class InvalidStateTransitionError(StateMachineError):
    """Raised when an illegal event is applied to the current state."""

    def __init__(self, current_state: WorkflowState, event: DomainEvent) -> None:
        super().__init__(
            f"Invalid transition attempted: State '{current_state.value}' does not accept event '{event.value}'."
        )
        self.current_state = current_state
        self.event = event


class GuardConditionFailedError(StateMachineError):
    """Raised when a state transition guard condition fails."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Guard condition failed: {message}")


class DeterministicFSM:
    """Authoritative Finite State Machine for workflow control."""

    def __init__(self) -> None:
        self._transition_listeners: list[
            Callable[[WorkflowState, WorkflowState, DomainEvent, dict[str, Any]], None]
        ] = []

    def add_listener(
        self,
        listener: Callable[[WorkflowState, WorkflowState, DomainEvent, dict[str, Any]], None],
    ) -> None:
        """Register a callback to observe state transitions."""
        self._transition_listeners.append(listener)

    def can_transition(self, current_state: WorkflowState, event: DomainEvent) -> bool:
        """Check if an event is syntactically valid from the current state."""
        return (current_state, event) in VALID_TRANSITIONS

    def evaluate_guards(
        self,
        current_state: WorkflowState,
        event: DomainEvent,
        context: dict[str, Any],
    ) -> None:
        """Verify programmatic guard conditions before allowing transition."""
        # Guard 1: UNDERSTANDING -> CONTEXT_DISCOVERING requires clean ambiguity checklist
        if current_state == WorkflowState.UNDERSTANDING and event == DomainEvent.SPEC_READY:
            spec: WorkItemSpec | None = context.get("spec")
            if spec and spec.ambiguity_checklist.has_blockers():
                raise GuardConditionFailedError(
                    f"WorkItemSpec contains blocking ambiguities: {spec.ambiguity_checklist.findings}. "
                    "Must escalate to HUMAN_ESCALATION via AMBIGUITY_ESCALATE."
                )

        # Guard 2: VALIDATION_GATE transitions require real validation evidence
        if current_state == WorkflowState.VALIDATION_GATE:
            val_run: ValidationRun | None = context.get("validation_run")
            if not val_run:
                raise GuardConditionFailedError(
                    "ValidationRun evidence is required to transition from VALIDATION_GATE."
                )

            if event == DomainEvent.GATE_PASS and not val_run.all_passed:
                raise GuardConditionFailedError(
                    "Cannot pass Validation Gate: real test execution reported failures."
                )

            if event == DomainEvent.GATE_FAIL_RETRY:
                retry_count = context.get("retry_count", 0)
                max_retries = context.get("max_retries", 3)
                if retry_count >= max_retries:
                    raise GuardConditionFailedError(
                        f"Retry limit ({max_retries}) reached. Must transition via GATE_FAIL_LIMIT."
                    )

            if event == DomainEvent.GATE_FAIL_LIMIT:
                retry_count = context.get("retry_count", 0)
                max_retries = context.get("max_retries", 3)
                if retry_count < max_retries:
                    raise GuardConditionFailedError(
                        f"Retry budget still available ({retry_count} of {max_retries})."
                    )

        # Guard 3: PR_QUALITY_GATE requires evidence-based QualityGateReport
        if current_state == WorkflowState.PR_QUALITY_GATE:
            report: QualityGateReport | None = context.get("quality_report")
            if not report:
                raise GuardConditionFailedError(
                    "QualityGateReport evidence is required to transition from PR_QUALITY_GATE."
                )

            if event == DomainEvent.QUALITY_PASS and not report.is_approved():
                raise GuardConditionFailedError(
                    "PR Quality Gate cannot be approved: criteria verification or diff checks failed."
                )

            if event == DomainEvent.QUALITY_FAIL_RETRY:
                retry_count = context.get("retry_count", 0)
                max_retries = context.get("max_retries", 3)
                if retry_count >= max_retries:
                    raise GuardConditionFailedError(
                        f"Retry limit ({max_retries}) reached. Must transition via QUALITY_FAIL_LIMIT."
                    )

            if event == DomainEvent.QUALITY_FAIL_LIMIT:
                retry_count = context.get("retry_count", 0)
                max_retries = context.get("max_retries", 3)
                if retry_count < max_retries:
                    raise GuardConditionFailedError(
                        f"Retry budget still available ({retry_count} of {max_retries})."
                    )

    def transition(
        self,
        current_state: WorkflowState,
        event: DomainEvent,
        context: dict[str, Any] | None = None,
    ) -> WorkflowState:
        """Execute deterministic transition if permitted and guards pass.

        Returns:
            The new WorkflowState.
        Raises:
            InvalidStateTransitionError: If the transition is not in the state table.
            GuardConditionFailedError: If a required condition is not met.
        """
        ctx = context or {}

        if current_state in TERMINAL_STATES:
            raise InvalidStateTransitionError(current_state, event)

        target_state = VALID_TRANSITIONS.get((current_state, event))
        if target_state is None:
            raise InvalidStateTransitionError(current_state, event)

        # Enforce programmatic guards
        self.evaluate_guards(current_state, event, ctx)

        logger.info(
            "FSM State Transition: %s --[%s]--> %s",
            current_state.value,
            event.value,
            target_state.value,
        )

        # Notify listeners (e.g. audit logger, db updater)
        for listener in self._transition_listeners:
            try:
                listener(current_state, target_state, event, ctx)
            except Exception as exc:
                logger.error("Error in state transition listener: %s", exc, exc_info=True)

        return target_state
