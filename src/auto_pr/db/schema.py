"""SQLAlchemy 2.0 Async declarative database schema for Auto PR Control Plane."""

from datetime import datetime, timezone
import uuid
from typing import Any
from sqlalchemy import (
    String,
    Text,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from auto_pr.db.session import Base


def utc_now() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class WorkItemRecord(Base):
    """Database representation of an external work item or ticket."""

    __tablename__ = "work_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="MANUAL")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    repository_url: Mapped[str] = mapped_column(String(500), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(100), nullable=False, default="main")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Relationships
    runs: Mapped[list["RunRecord"]] = relationship("RunRecord", back_populates="work_item")


class RunRecord(Base):
    """Authoritative persistent execution run for a work item."""

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    work_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    current_state: Mapped[str] = mapped_column(
        String(50), nullable=False, default="SUBMITTED", index=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    sandbox_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    work_item: Mapped["WorkItemRecord"] = relationship("WorkItemRecord", back_populates="runs")
    state_history: Mapped[list["StateHistoryRecord"]] = relationship(
        "StateHistoryRecord", back_populates="run", cascade="all, delete-orphan"
    )
    agent_executions: Mapped[list["AgentExecutionRecord"]] = relationship(
        "AgentExecutionRecord", back_populates="run", cascade="all, delete-orphan"
    )
    change_sets: Mapped[list["ChangeSetRecord"]] = relationship(
        "ChangeSetRecord", back_populates="run", cascade="all, delete-orphan"
    )
    validation_runs: Mapped[list["ValidationRunRecord"]] = relationship(
        "ValidationRunRecord", back_populates="run", cascade="all, delete-orphan"
    )
    retry_attempts: Mapped[list["RetryAttemptRecord"]] = relationship(
        "RetryAttemptRecord", back_populates="run", cascade="all, delete-orphan"
    )
    human_interventions: Mapped[list["HumanInterventionRecord"]] = relationship(
        "HumanInterventionRecord", back_populates="run", cascade="all, delete-orphan"
    )
    quality_gate_results: Mapped[list["QualityGateResultRecord"]] = relationship(
        "QualityGateResultRecord", back_populates="run", cascade="all, delete-orphan"
    )
    pull_request: Mapped["PullRequestRecord | None"] = relationship(
        "PullRequestRecord", back_populates="run", uselist=False, cascade="all, delete-orphan"
    )
    audit_events: Mapped[list["AuditEventRecord"]] = relationship(
        "AuditEventRecord", back_populates="run", cascade="all, delete-orphan"
    )


class StateHistoryRecord(Base):
    """Historical record of all workflow state transitions."""

    __tablename__ = "state_history"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_state: Mapped[str] = mapped_column(String(50), nullable=False)
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    event: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    run: Mapped["RunRecord"] = relationship("RunRecord", back_populates="state_history")


class AgentExecutionRecord(Base):
    """Traceable execution record for a specialized agent turn."""

    __tablename__ = "agent_executions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="SUCCESS")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped["RunRecord"] = relationship("RunRecord", back_populates="agent_executions")


class ChangeSetRecord(Base):
    """Record of file modifications produced by Implementation Agent."""

    __tablename__ = "change_sets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    patches: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    commit_message: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped["RunRecord"] = relationship("RunRecord", back_populates="change_sets")


class ValidationRunRecord(Base):
    """Persistent evidence of real execution validation runs."""

    __tablename__ = "validation_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    command_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    all_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped["RunRecord"] = relationship("RunRecord", back_populates="validation_runs")


class RetryAttemptRecord(Base):
    """Persistent log of retry attempts, root cause failures, and hypotheses."""

    __tablename__ = "retry_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    failure_type: Mapped[str] = mapped_column(String(100), nullable=False)
    hypothesis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped["RunRecord"] = relationship("RunRecord", back_populates="retry_attempts")


class HumanInterventionRecord(Base):
    """Persistent record of human escalation requests and guidance."""

    __tablename__ = "human_interventions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    diagnostic_details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prompt_to_human: Mapped[str] = mapped_column(Text, nullable=False)
    human_guidance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped["RunRecord"] = relationship("RunRecord", back_populates="human_interventions")


class QualityGateResultRecord(Base):
    """Persistent record of PR Quality Gate evidence-based evaluations."""

    __tablename__ = "quality_gate_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    verdict: Mapped[str] = mapped_column(String(50), nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped["RunRecord"] = relationship("RunRecord", back_populates="quality_gate_results")


class PullRequestRecord(Base):
    """Persistent record of created Pull Requests."""

    __tablename__ = "pull_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    branch_name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_branch: Mapped[str] = mapped_column(String(100), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    run: Mapped["RunRecord"] = relationship("RunRecord", back_populates="pull_request")


class AuditEventRecord(Base):
    """Append-only, immutable audit log of all events across runs."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="System")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    run: Mapped["RunRecord | None"] = relationship("RunRecord", back_populates="audit_events")
