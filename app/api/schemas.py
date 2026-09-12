"""HTTP request/response models. Separate from domain models on purpose: the
wire format is allowed to evolve without dragging the agent's types with it."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.agent.state import ApprovalState, RunStatus
from app.domain.models import IncidentAnalysis


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=8, max_length=2000, description="What to investigate, in prose.")
    target_service: str | None = Field(
        default=None,
        max_length=200,
        description="Optional override; otherwise inferred from the task.",
    )


class ToolCallView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tool: str
    arguments: dict
    started_at: datetime
    duration_ms: float
    attempt: int
    ok: bool
    error: str | None = None
    result_summary: str = ""


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task: str
    target_service: str | None
    status: RunStatus
    approval_state: ApprovalState
    step_count: int
    tool_call_count: int
    created_at: datetime
    finished_at: datetime | None = None
    final_result: str | None = None


class RunDetail(RunSummary):
    analysis: IncidentAnalysis | None = None
    tool_calls: list[ToolCallView] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
