"""The select → execute → evaluate cycle.

This is the part of the workflow that is not a pipeline. The planner proposes,
the executor disposes, and evaluation decides whether to go round again. Each
of the three is a separate node for a reason worth stating: a decision, its
effect and the judgement about its effect are different things, and putting
them in one node would make it impossible to see — in the audit trail or in a
test — which of them went wrong.

Termination is not left to the model. The loop ends when the planner asks for
nothing, when the tool budget runs out, when the iteration cap is reached, or
when a round produces no new evidence. Any one of those is enough; the model's
opinion is only the first.
"""

from __future__ import annotations

from typing import Any, Literal

import structlog

from app.agent.guardrails import BudgetExhausted, Guardrails
from app.agent.planner import Planner
from app.agent.state import AgentState, CollectedContext, RunError
from app.agent.tools.base import ToolRegistry, ToolRequest
from app.agent.tools.executor import ToolExecutor, ToolInvocation
from app.agent.tools.schemas import (
    AlertsResult,
    CommitsResult,
    DeploymentsResult,
    ErrorGroupsResult,
    MetricsResult,
    PullRequestResult,
)
from app.domain.models import Evidence, EvidenceKind

log = structlog.get_logger(__name__)

#: Hard ceiling on cycles, independent of the tool budget. A planner that asks
#: for nothing executable would otherwise spin without spending the budget.
MAX_LOOP_ITERATIONS = 4

#: Which kind of evidence each tool produces. Used to classify findings so the
#: analysis can separate a symptom (metric, log) from a cause (commit, deploy).
EVIDENCE_KINDS: dict[str, EvidenceKind] = {
    "get_service_metrics": EvidenceKind.METRIC,
    "get_recent_alerts": EvidenceKind.ALERT,
    "get_recent_deployments": EvidenceKind.DEPLOYMENT,
    "get_commits": EvidenceKind.COMMIT,
    "get_pull_request": EvidenceKind.COMMIT,
    "get_error_groups": EvidenceKind.LOG,
}


# ── select_tool ──────────────────────────────────────────────────────────────


def make_select_tool_node(planner: Planner, registry: ToolRegistry, guardrails: Guardrails):
    """Ask the planner for the next step, inside the remaining budget."""

    async def select_tool_node(state: AgentState) -> AgentState:
        step = state.get("step_count", 0) + 1
        spent = state.get("tool_call_count", 0)
        remaining = max(guardrails.max_tool_calls - spent, 0)

        try:
            guardrails.check_budget(tool_calls=spent, steps=state.get("step_count", 0))
        except BudgetExhausted as exc:
            return AgentState(
                current_step="select_tool",
                step_count=step,
                pending_requests=[],
                tool_budget_remaining=0,
                planner_rationale=str(exc),
                observations=[{"node": "select_tool", "stopped": str(exc)}],
            )

        available = guardrails.available(registry)
        plan = await planner.plan({**state, "tool_budget_remaining": remaining}, available)

        errors = (
            [
                RunError(
                    node="select_tool",
                    kind="planner_failed",
                    message=plan.error,
                    recoverable=True,
                )
            ]
            if plan.error
            else []
        )
        log.info(
            "agent.plan",
            run_id=state.get("run_id"),
            requested=[r.tool for r in plan.requests],
            rationale=plan.rationale[:200],
        )
        return AgentState(
            current_step="select_tool",
            step_count=step,
            pending_requests=list(plan.requests[:remaining]),
            tool_budget_remaining=remaining,
            planner_rationale=plan.rationale,
            errors=errors,
            llm_calls=1 if plan.usage.latency_ms else 0,
            input_tokens=plan.usage.input_tokens,
            output_tokens=plan.usage.output_tokens,
            observations=[
                {
                    "node": "select_tool",
                    "requested": [r.tool for r in plan.requests],
                    "rationale": plan.rationale,
                }
            ],
        )

    return select_tool_node


def route_after_selection(state: AgentState) -> Literal["execute_tool", "generate_analysis"]:
    """The planner asking for nothing is the normal way out of the loop."""
    return "execute_tool" if state.get("pending_requests") else "generate_analysis"


# ── execute_tool ─────────────────────────────────────────────────────────────


def make_execute_tool_node(registry: ToolRegistry, guardrails: Guardrails):
    """Run what the planner asked for, under policy, and absorb the results."""

    async def execute_tool_node(state: AgentState) -> AgentState:
        requests: list[ToolRequest] = list(state.get("pending_requests") or [])
        executor = ToolExecutor.resume(registry, guardrails, state.get("tool_calls", []))
        defaults = _window_defaults(state)

        # Copy-on-write: LangGraph merges returned values, and mutating the
        # context in place would make a partial failure invisible in the diff.
        context = (state.get("context") or CollectedContext()).model_copy(deep=True)

        records, evidence, observations, errors = [], [], [], []
        for request in requests:
            invocation = await executor.execute(request, defaults=defaults)
            records.append(invocation.record)
            observations.append(
                {
                    "node": "execute_tool",
                    "tool": request.tool,
                    "reason": request.reason,
                    "ok": invocation.ok,
                    "summary": invocation.digest[:300] or invocation.error,
                }
            )
            if not invocation.ok:
                errors.append(
                    RunError(
                        node="execute_tool",
                        kind="tool_failed",
                        message=f"{request.tool}: {invocation.error}",
                    )
                )
                continue
            _absorb(context, invocation)
            evidence.append(
                Evidence(
                    kind=EVIDENCE_KINDS.get(request.tool, EvidenceKind.DOCUMENT),
                    summary=invocation.digest,
                    source_tool=request.tool,
                    reference=_reference(request),
                )
            )

        return AgentState(
            current_step="execute_tool",
            step_count=state.get("step_count", 0) + 1,
            tool_call_count=state.get("tool_call_count", 0) + len(records),
            tool_calls=records,
            evidence=evidence,
            context=context,
            pending_requests=[],
            errors=errors,
            observations=observations,
        )

    return execute_tool_node


# ── evaluate_observation ─────────────────────────────────────────────────────


async def evaluate_observation_node(state: AgentState) -> AgentState:
    """Decide whether the last round changed anything worth another round."""
    iterations = state.get("loop_iterations", 0) + 1
    recent = state.get("observations", [])[-5:]
    produced_evidence = any(o.get("node") == "execute_tool" and o.get("ok") for o in recent)
    return AgentState(
        current_step="evaluate_observation",
        step_count=state.get("step_count", 0) + 1,
        loop_iterations=iterations,
        observations=[
            {
                "node": "evaluate_observation",
                "iteration": iterations,
                "produced_evidence": produced_evidence,
            }
        ],
    )


def make_route_after_evaluation(guardrails: Guardrails):
    """Routing is a pure function of state, so it is unit-testable alone."""

    def route_after_evaluation(state: AgentState) -> Literal["select_tool", "generate_analysis"]:
        if state.get("loop_iterations", 0) >= MAX_LOOP_ITERATIONS:
            return "generate_analysis"
        if state.get("tool_call_count", 0) >= guardrails.max_tool_calls:
            return "generate_analysis"
        if state.get("step_count", 0) >= guardrails.max_workflow_steps:
            return "generate_analysis"
        last = next(
            (
                o
                for o in reversed(state.get("observations", []))
                if o.get("node") == "evaluate_observation"
            ),
            None,
        )
        # A round that produced nothing usable will not produce anything next
        # time either — the inputs to the planner are unchanged.
        if last is not None and not last.get("produced_evidence"):
            return "generate_analysis"
        return "select_tool"

    return route_after_evaluation


# ── helpers ──────────────────────────────────────────────────────────────────


def _window_defaults(state: AgentState) -> dict[str, Any]:
    return {"start": state.get("window_start"), "end": state.get("window_end")}


def _reference(request: ToolRequest) -> str:
    """A short, stable pointer back to what produced a piece of evidence."""
    interesting = {k: v for k, v in request.arguments.items() if k not in ("start", "end")}
    return "/".join(str(v) for _, v in sorted(interesting.items())) or request.tool


def _absorb(context: CollectedContext, invocation: ToolInvocation) -> None:
    """Merge a typed tool result into the machine-readable context.

    Results are merged rather than replaced so a second call for a different
    metric or a wider window adds to what is known instead of erasing it.
    """
    result = invocation.result
    match result:
        case MetricsResult():
            context.metrics[result.series.metric] = result.series
        case DeploymentsResult():
            context.deployments = _merge(
                context.deployments, result.deployments, key=lambda d: (d.service, d.version)
            )
        case CommitsResult():
            context.commits = _merge(context.commits, result.commits, key=lambda c: c.sha)
        case ErrorGroupsResult():
            context.error_groups = _merge(
                context.error_groups, result.groups, key=lambda g: g.error_type
            )
        case AlertsResult():
            context.alerts = _merge(
                context.alerts, result.alerts, key=lambda a: (a.name, a.fired_at)
            )
        case PullRequestResult():
            pass  # Pull requests inform the narrative; nothing correlates on them yet.


def _merge[T](existing: list[T], incoming: tuple[T, ...], *, key) -> list[T]:
    seen = {key(item) for item in existing}
    return existing + [item for item in incoming if key(item) not in seen]
