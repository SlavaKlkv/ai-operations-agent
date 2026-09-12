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

from app.agent.tools.base import ToolRequest
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
    #: True when the result came from the cache rather than the provider.
    #: Kept on the record so evaluation can tell a cheap run from a fast one.
    cached: bool = False


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
    #: How many tool calls the guardrails still allow. Shown to the planner so
    #: it can spend a scarce budget on the evidence that matters most.
    tool_budget_remaining: int
    #: Iterations of the select → execute → evaluate cycle.
    loop_iterations: int
    #: What the planner asked for, between the decision and its execution.
    pending_requests: list[ToolRequest]
    #: Why the planner stopped, in its own words. Part of the audit answer to
    #: "why did the agent conclude here".
    planner_rationale: str

    # Model accounting
    llm_calls: Annotated[int, operator.add]
    input_tokens: Annotated[int, operator.add]
    output_tokens: Annotated[int, operator.add]

    # Output
    analysis: IncidentAnalysis | None
    proposed_actions: list[ProposedAction]
    approval_state: ApprovalState
    #: Who decided, and what they said. Recorded on the run because "the
    #: agent created an issue" is never a complete answer to "who did this".
    approved_by: str | None
    approval_note: str
    #: What the executed write returned, so the effect is linked to its
    #: approval rather than only to a log line.
    action_result: dict[str, Any] | None
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
        tool_budget_remaining=0,
        loop_iterations=0,
        pending_requests=[],
        planner_rationale="",
        llm_calls=0,
        input_tokens=0,
        output_tokens=0,
        analysis=None,
        proposed_actions=[],
        approval_state=ApprovalState.NOT_REQUIRED,
        approved_by=None,
        approval_note="",
        action_result=None,
        final_result=None,
    )
