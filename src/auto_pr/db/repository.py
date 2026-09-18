"""Repository operations for persisting runs, agent executions, and audit records."""

import uuid
from typing import Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from auto_pr.core.states import WorkflowState, DomainEvent
from auto_pr.core.models import (
    WorkItemInput,
    ChangeSet,
    ValidationRun,
    QualityGateReport,
    PullRequestInfo,
)
from auto_pr.security.redaction import redact_data
from auto_pr.db.schema import (
    WorkItemRecord,
    RunRecord,
    StateHistoryRecord,
    AgentExecutionRecord,
    ChangeSetRecord,
    ValidationRunRecord,
    RetryAttemptRecord,
    HumanInterventionRecord,
    QualityGateResultRecord,
    PullRequestRecord,
    AuditEventRecord,
    utc_now,
)


class WorkflowRepository:
    """Async repository managing state, runs, evidence, and audit logs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_work_item(self, item: WorkItemInput) -> WorkItemRecord:
        """Create and persist a new work item."""
        record = WorkItemRecord(
            external_id=item.external_id,
            source=item.source,
            title=item.title,
            raw_description=item.raw_description,
            repository_url=item.repository_url,
            base_branch=item.base_branch,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def create_run(
        self,
        work_item_id: uuid.UUID,
        max_retries: int = 3,
        branch_name: str | None = None,
    ) -> RunRecord:
        """Create and initialize a new execution run for a work item."""
        run = RunRecord(
            work_item_id=work_item_id,
            current_state=WorkflowState.SUBMITTED.value,
            retry_count=0,
            max_retries=max_retries,
            branch_name=branch_name,
        )
        self.session.add(run)
        await self.session.flush()

        # Record initial state transition in history
        history = StateHistoryRecord(
            run_id=run.id,
            from_state="NONE",
            to_state=WorkflowState.SUBMITTED.value,
            event="CREATE_RUN",
            details={"work_item_id": str(work_item_id)},
        )
        self.session.add(history)
        await self.session.flush()

        # Record initial audit event
        await self.record_audit_event(
            run_id=run.id,
            event_name="RUN_CREATED",
            actor="ControlPlane",
            payload={"work_item_id": str(work_item_id), "max_retries": max_retries},
        )
        return run

    async def get_run(self, run_id: uuid.UUID) -> RunRecord | None:
        """Retrieve a run with state history and child relationships preloaded."""
        stmt = (
            select(RunRecord)
            .where(RunRecord.id == run_id)
            .options(
                selectinload(RunRecord.work_item),
                selectinload(RunRecord.state_history),
                selectinload(RunRecord.agent_executions),
                selectinload(RunRecord.change_sets),
                selectinload(RunRecord.validation_runs),
                selectinload(RunRecord.retry_attempts),
                selectinload(RunRecord.human_interventions),
                selectinload(RunRecord.quality_gate_results),
                selectinload(RunRecord.pull_request),
                selectinload(RunRecord.audit_events),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_run_state(
        self,
        run_id: uuid.UUID,
        from_state: WorkflowState,
        to_state: WorkflowState,
        event: DomainEvent,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Atomically transition run state, record history, and append audit event."""
        run = await self.session.get(RunRecord, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found.")

        run.current_state = to_state.value
        run.updated_at = utc_now()
        if to_state in (WorkflowState.COMPLETED, WorkflowState.FAILED):
            run.completed_at = utc_now()

        safe_details = redact_data(details or {})
        history = StateHistoryRecord(
            run_id=run_id,
            from_state=from_state.value,
            to_state=to_state.value,
            event=event.value,
            details=safe_details,
        )
        self.session.add(history)

        await self.record_audit_event(
            run_id=run_id,
            event_name=f"STATE_TRANSITION_{event.value}",
            actor="ControlPlane",
            payload={
                "from_state": from_state.value,
                "to_state": to_state.value,
                "event": event.value,
                "details": safe_details,
            },
        )
        await self.session.flush()

    async def increment_retry_count(self, run_id: uuid.UUID) -> int:
        """Increment retry counter for a run and return new count."""
        run = await self.session.get(RunRecord, run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found.")
        run.retry_count += 1
        await self.session.flush()
        return run.retry_count

    async def record_agent_execution(
        self,
        run_id: uuid.UUID,
        agent_name: str,
        model_name: str,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        duration_ms: int = 0,
        status: str = "SUCCESS",
    ) -> AgentExecutionRecord:
        """Record an agent execution turn with automatic secret redaction."""
        record = AgentExecutionRecord(
            run_id=run_id,
            agent_name=agent_name,
            model_name=model_name,
            input_payload=redact_data(input_payload),
            output_payload=redact_data(output_payload),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            duration_ms=duration_ms,
            status=status,
        )
        self.session.add(record)
        await self.session.flush()

        await self.record_audit_event(
            run_id=run_id,
            event_name="AGENT_EXECUTED",
            actor=agent_name,
            payload={
                "agent_name": agent_name,
                "model_name": model_name,
                "tokens": prompt_tokens + completion_tokens,
                "duration_ms": duration_ms,
                "status": status,
            },
        )
        return record

    async def record_change_set(self, run_id: uuid.UUID, changeset: ChangeSet) -> ChangeSetRecord:
        """Record a proposed changeset."""
        record = ChangeSetRecord(
            run_id=run_id,
            iteration=changeset.iteration,
            summary=changeset.summary,
            patches=[patch.model_dump() for patch in changeset.patches],
            commit_message=changeset.commit_message,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def record_validation_run(
        self, run_id: uuid.UUID, val_run: ValidationRun
    ) -> ValidationRunRecord:
        """Record real validation run execution results."""
        record = ValidationRunRecord(
            run_id=run_id,
            iteration=val_run.iteration,
            command_results=[res.model_dump() for res in val_run.command_results],
            all_passed=val_run.all_passed,
            duration_ms=val_run.duration_ms,
        )
        self.session.add(record)
        await self.session.flush()

        await self.record_audit_event(
            run_id=run_id,
            event_name="VALIDATION_RUN_RECORDED",
            actor="ValidationEngine",
            payload={
                "iteration": val_run.iteration,
                "all_passed": val_run.all_passed,
                "command_count": len(val_run.command_results),
                "duration_ms": val_run.duration_ms,
            },
        )
        return record

    async def record_retry_attempt(
        self,
        run_id: uuid.UUID,
        iteration: int,
        failure_type: str,
        hypothesis: dict[str, Any],
    ) -> RetryAttemptRecord:
        """Record a debugging diagnosis and retry attempt."""
        record = RetryAttemptRecord(
            run_id=run_id,
            iteration=iteration,
            failure_type=failure_type,
            hypothesis=redact_data(hypothesis),
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def record_human_intervention(
        self,
        run_id: uuid.UUID,
        reason: str,
        prompt_to_human: str,
        diagnostic_details: dict[str, Any],
    ) -> HumanInterventionRecord:
        """Record a human escalation request."""
        record = HumanInterventionRecord(
            run_id=run_id,
            reason=reason,
            prompt_to_human=prompt_to_human,
            diagnostic_details=redact_data(diagnostic_details),
            resolved=False,
        )
        self.session.add(record)
        await self.session.flush()

        await self.record_audit_event(
            run_id=run_id,
            event_name="HUMAN_ESCALATION_TRIGGERED",
            actor="ControlPlane",
            payload={"reason": reason},
        )
        return record

    async def resolve_human_intervention(
        self,
        intervention_id: uuid.UUID,
        guidance: dict[str, Any],
    ) -> None:
        """Resolve a human intervention request with supervisor guidance."""
        record = await self.session.get(HumanInterventionRecord, intervention_id)
        if not record:
            raise ValueError(f"Intervention {intervention_id} not found.")
        record.human_guidance = redact_data(guidance)
        record.resolved = True
        await self.session.flush()

        await self.record_audit_event(
            run_id=record.run_id,
            event_name="HUMAN_INTERVENTION_RESOLVED",
            actor="HumanSupervisor",
            payload={"decision": guidance.get("decision", "RESUME")},
        )

    async def record_quality_gate(
        self, run_id: uuid.UUID, report: QualityGateReport
    ) -> QualityGateResultRecord:
        """Record an evidence-based PR Quality Gate report."""
        record = QualityGateResultRecord(
            run_id=run_id,
            verdict=report.verdict,
            report=report.model_dump(),
        )
        self.session.add(record)
        await self.session.flush()

        await self.record_audit_event(
            run_id=run_id,
            event_name="QUALITY_GATE_EVALUATED",
            actor="PRQualityAgent",
            payload={
                "verdict": report.verdict,
                "all_criteria_satisfied": report.all_criteria_satisfied,
                "diff_risk": report.diff_risk.risk_level,
            },
        )
        return record

    async def record_pull_request(
        self, run_id: uuid.UUID, pr_info: PullRequestInfo
    ) -> PullRequestRecord:
        """Record created Pull Request details."""
        record = PullRequestRecord(
            run_id=run_id,
            branch_name=pr_info.branch_name,
            base_branch=pr_info.base_branch,
            commit_sha=pr_info.commit_sha,
            title=pr_info.title,
            body_markdown=pr_info.body_markdown,
            pr_number=pr_info.pr_number,
            pr_url=pr_info.pr_url,
        )
        self.session.add(record)
        await self.session.flush()

        await self.record_audit_event(
            run_id=run_id,
            event_name="PULL_REQUEST_RECORDED",
            actor="PRGenerator",
            payload={
                "branch_name": pr_info.branch_name,
                "commit_sha": pr_info.commit_sha,
                "pr_url": pr_info.pr_url,
            },
        )
        return record

    async def record_audit_event(
        self,
        run_id: uuid.UUID | None,
        event_name: str,
        actor: str = "System",
        payload: dict[str, Any] | None = None,
    ) -> AuditEventRecord:
        """Append an immutable, sanitized audit record."""
        record = AuditEventRecord(
            run_id=run_id,
            event_name=event_name,
            actor=actor,
            payload=redact_data(payload or {}),
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_audit_trail(self, run_id: uuid.UUID) -> list[AuditEventRecord]:
        """Retrieve the ordered audit log for a run."""
        stmt = (
            select(AuditEventRecord)
            .where(AuditEventRecord.run_id == run_id)
            .order_by(AuditEventRecord.timestamp.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
