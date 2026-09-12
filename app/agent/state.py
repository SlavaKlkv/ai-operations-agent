"""Explicit workflow state.

The state is the single source of truth for a run. Nothing important lives
only inside a prompt: every observation, tool call and decision the graph makes
is written here, which is what makes a run replayable and auditable.
"""

from __future__ import annotations

import operator
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import (
    Alert,
    Commit,
    Deployment,
    ErrorGroup,
    Evidence,
    Hypothesis,
    IncidentAnalysis,
    MetricSeries,
)


class RunStatus(StrEnum):
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class ApprovalState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ToolCallRecord(BaseModel):
    """One executed tool call, kept for audit and evaluation."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    duration_ms: float
    ok: bool
    error: str | None = None
    result_summary: str = ""
    attempt: int = 1


class ProposedAction(BaseModel):
    """A write operation the agent wants to perform, pending approval."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    requires_approval: bool = True


class CollectedContext(BaseModel):
    """Raw-but-typed observations, kept so later nodes can re-reason over them.

    Evidence is the human-readable trace of what was found; this is the machine
    -readable counterpart that correlation and analysis actually compute on.
    """

    model_config = ConfigDict(extra="forbid")

    metrics: dict[str, MetricSeries] = Field(default_factory=dict)
    deployments: list[Deployment] = Field(default_factory=list)
    commits: list[Commit] = Field(default_factory=list)
    error_groups: list[ErrorGroup] = Field(default_factory=list)
    alerts: list[Alert] = Field(default_factory=list)


class RunError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: str
    kind: str
    message: str
    recoverable: bool = True


class AgentState(TypedDict, total=False):
    """LangGraph state. Reducers make concurrent/looping writes additive."""

    # Input
    run_id: str
    task: str
    target_service: str | None
    window_start: datetime | None
    window_end: datetime | None

    # Accumulated observations
    observations: Annotated[list[dict[str, Any]], operator.add]
    tool_calls: Annotated[list[ToolCallRecord], operator.add]
    evidence: Annotated[list[Evidence], operator.add]
    hypotheses: list[Hypothesis]
    context: CollectedContext
    errors: Annotated[list[RunError], operator.add]

    # Control
    current_step: str
    step_count: int
    tool_call_count: int
    status: RunStatus

    # Output
    analysis: IncidentAnalysis | None
    proposed_actions: list[ProposedAction]
    approval_state: ApprovalState
    final_result: str | None


def initial_state(run_id: str, task: str, target_service: str | None = None) -> AgentState:
    return AgentState(
        run_id=run_id,
        task=task,
        target_service=target_service,
        observations=[],
        tool_calls=[],
        evidence=[],
        hypotheses=[],
        context=CollectedContext(),
        errors=[],
        current_step="start",
        step_count=0,
        tool_call_count=0,
        status=RunStatus.RUNNING,
        analysis=None,
        proposed_actions=[],
        approval_state=ApprovalState.NOT_REQUIRED,
        final_result=None,
    )
