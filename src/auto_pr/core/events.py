"""Domain events carrying validated payloads through the Control Plane."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from auto_pr.core.states import DomainEvent


class WorkflowEventPayload(BaseModel):
    """Base event payload carrying metadata and contextual payload."""

    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    event_type: DomainEvent
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = Field(default_factory=dict)
    actor: str = "ControlPlane"
