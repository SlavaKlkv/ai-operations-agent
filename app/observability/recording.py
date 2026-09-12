"""Turning a finished run into metrics and a readable trace.

Kept apart from the graph on purpose. Nodes return state; this module reads
that state and decides what is worth counting. The alternative — scattering
``counter.inc()`` through the nodes — makes the workflow harder to read and
ties the agent's logic to whichever metrics backend is in fashion.

The trace is the answer to "why did the agent conclude this". It records the
observable decisions: which node ran, which tool was called with which
arguments, what came back in summary, and where the workflow branched. It
does not record model reasoning, because the system does not depend on it —
what the agent *did* is auditable, what it "thought" is not evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from app.agent.state import AgentState, ApprovalState, RunStatus
from app.observability import metrics

log = structlog.get_logger(__name__)

WRITE_TOOLS = frozenset({"create_issue", "add_issue_comment"})


def record_run(state: AgentState, *, duration_seconds: float) -> None:
    """Count one finished or paused investigation."""
    service = state.get("target_service") or "unknown"
    status = state.get("status", RunStatus.RUNNING)

    metrics.runs_finished.labels(service=service, status=str(status)).inc()
    metrics.run_duration.labels(service=service).observe(duration_seconds)
    metrics.run_tool_calls.observe(state.get("tool_call_count", 0))

    analysis = state.get("analysis")
    if analysis is not None:
        metrics.run_confidence.observe(analysis.confidence)

    for call in state.get("tool_calls", []):
        metrics.tool_calls.labels(tool=call.tool, outcome="ok" if call.ok else "error").inc()
        metrics.tool_duration.labels(tool=call.tool).observe(call.duration_ms / 1000)

    _record_model_usage(state)
    _record_write_safety(state)


def record_run_started(service: str | None) -> None:
    metrics.runs_started.labels(service=service or "unknown").inc()


def record_decision(*, approved: bool) -> None:
    metrics.approvals.labels(decision="approved" if approved else "rejected").inc()


def _record_model_usage(state: AgentState) -> None:
    calls = state.get("llm_calls", 0)
    failures = sum(1 for e in state.get("errors", []) if e.kind in ("planner_failed", "llm_failed"))
    if calls:
        metrics.llm_calls.labels(outcome="ok").inc(calls)
    if failures:
        metrics.llm_calls.labels(outcome="error").inc(failures)

    if tokens := state.get("input_tokens", 0):
        metrics.llm_tokens.labels(direction="input").inc(tokens)
    if tokens := state.get("output_tokens", 0):
        metrics.llm_tokens.labels(direction="output").inc(tokens)


def _record_write_safety(state: AgentState) -> None:
    """The one counter that should never move.

    Checked from the recorded facts rather than trusted from a flag: if a
    write appears in the call log and the run does not carry an approval, the
    gate failed, and the metric has to say so loudly enough to page someone.
    """
    if state.get("approval_state") is ApprovalState.APPROVED:
        return
    for call in state.get("tool_calls", []):
        if call.tool in WRITE_TOOLS and call.ok:
            metrics.unapproved_writes.labels(tool=call.tool).inc()
            log.error(
                "agent.unapproved_write",
                run_id=state.get("run_id"),
                tool=call.tool,
                approval_state=str(state.get("approval_state")),
            )


def record_integration_health(statuses, *, durable_checkpointer: bool) -> None:
    for status in statuses:
        metrics.mcp_server_up.labels(server=status.name, required=str(status.required).lower()).set(
            1 if status.connected else 0
        )
    metrics.checkpointer_durable.set(1 if durable_checkpointer else 0)


# ── Trace ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TraceEntry:
    """One observable thing the workflow did."""

    step: int
    node: str
    detail: dict[str, Any]


def build_trace(state: AgentState) -> list[TraceEntry]:
    """Reconstruct the run from its observations, in order.

    Observations are appended by every node as it runs, so replaying them is
    the graph execution: nodes visited, tools called, branches taken. This is
    what makes "why did the agent arrive here" answerable after the fact
    without re-running anything.
    """
    return [
        TraceEntry(
            step=index,
            node=str(observation.get("node", observation.get("tool", "?"))),
            detail={k: v for k, v in observation.items() if k != "node"},
        )
        for index, observation in enumerate(state.get("observations", []), start=1)
    ]


def render_trace(state: AgentState) -> str:
    """The trace as text, for a terminal or an issue comment."""
    lines = [f"run {state.get('run_id')} — {state.get('status')}"]
    for entry in build_trace(state):
        summary = ", ".join(f"{k}={_short(v)}" for k, v in entry.detail.items() if v is not None)
        lines.append(f"  {entry.step:>2}. {entry.node}: {summary}")
    if analysis := state.get("analysis"):
        lines.append(f"  → {analysis.confidence:.2f} {analysis.summary}")
    return "\n".join(lines)


def _short(value: Any, limit: int = 120) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"
