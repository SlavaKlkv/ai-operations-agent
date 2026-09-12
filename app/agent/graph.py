"""Graph assembly.

The shape of the workflow is the design document. Reading it should answer
"what can this agent do, and what can it not do" without reading a prompt::

    START
      ↓
    analyze_task
      ↓
    collect_initial_context ──(no usable signal)──→ insufficient_context ──→ END
      ↓
    correlate
      ↓
    select_tool ──(nothing more to ask)────────────────────┐
      ↓                                                    │
    execute_tool                                           │
      ↓                                                    ↓
    evaluate_observation ──(more to learn)──→ select_tool  │
      └──(enough / out of budget)─────────────────────────→ generate_analysis
                                                             ↓
                                                           final_response → END

Three properties hold by construction, not by instruction:

*The deterministic work happens first.* Baseline collection and correlation
run before the model is consulted at all, so the planner reasons about facts
rather than deciding how to find them.

*Every cycle has an exit that the model does not control.* The loop back to
``select_tool`` is guarded by a routing function that checks budgets and
progress; the planner can only ever shorten the loop, never extend it.

*The model is optional.* Pass no chat model and every node still runs, using
its deterministic counterpart. That is what makes the graph testable and what
makes a provider outage a degradation rather than an outage.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from app.adapters.base import CodeProvider, LogProvider, MonitoringProvider
from app.adapters.mock.providers import (
    MockCodeProvider,
    MockLogProvider,
    MockMonitoringProvider,
)
from app.agent.guardrails import Guardrails
from app.agent.llm import build_chat_model
from app.agent.nodes.analyze_task import analyze_task_node
from app.agent.nodes.build_analysis import make_build_analysis_node
from app.agent.nodes.collect_context import make_collect_context_node
from app.agent.nodes.correlate import make_correlate_node
from app.agent.nodes.investigate import (
    evaluate_observation_node,
    make_execute_tool_node,
    make_route_after_evaluation,
    make_select_tool_node,
    route_after_selection,
)
from app.agent.planner import HeuristicPlanner, LLMPlanner, Planner
from app.agent.state import AgentState, RunStatus
from app.agent.tools.catalog import build_registry


def has_enough_context(state: AgentState) -> Literal["correlate", "insufficient_context"]:
    """Gate between collection and analysis.

    Written as a pure function of state so routing can be unit-tested without
    running the graph, which is most of the value of keeping state explicit.
    """
    if state.get("status") is RunStatus.FAILED:
        return "insufficient_context"
    context = state.get("context")
    if context is None or not context.metrics:
        return "insufficient_context"
    return "correlate"


async def insufficient_context_node(state: AgentState) -> AgentState:
    reasons = [e.message for e in state.get("errors", [])] or [
        "no monitoring data was available for the requested service and window"
    ]
    return AgentState(
        current_step="insufficient_context",
        step_count=state.get("step_count", 0) + 1,
        status=RunStatus.FAILED,
        final_result=("The investigation stopped before analysis: " + "; ".join(reasons) + "."),
    )


async def finalize_node(state: AgentState) -> AgentState:
    analysis = state.get("analysis")
    return AgentState(
        current_step="final_response",
        step_count=state.get("step_count", 0) + 1,
        status=RunStatus.COMPLETED,
        final_result=analysis.summary if analysis else "No analysis was produced.",
    )


def build_graph(
    *,
    monitoring: MonitoringProvider | None = None,
    code: CodeProvider | None = None,
    logs: LogProvider | None = None,
    model: BaseChatModel | None = None,
    planner: Planner | None = None,
    guardrails: Guardrails | None = None,
    use_llm: bool = True,
):
    """Compile the workflow.

    Every collaborator is injectable because every one of them is something a
    test, an evaluation scenario or a deployment needs to substitute: mock or
    MCP-backed providers, a scripted or real model, a tighter policy.

    ``use_llm=False`` forces the deterministic path even when credentials are
    present — the evaluation harness uses it as the baseline to measure the
    model-driven agent against.
    """
    monitoring = monitoring or MockMonitoringProvider()
    code = code or MockCodeProvider()
    logs = logs or MockLogProvider()
    guardrails = guardrails or Guardrails()

    if use_llm and model is None:
        model = build_chat_model()
    if not use_llm:
        model = None
    planner = planner or (LLMPlanner(model) if model is not None else HeuristicPlanner())

    registry = build_registry(monitoring, code, logs)
    timeout = guardrails.tool_timeout_seconds

    builder = StateGraph(AgentState)
    builder.add_node("analyze_task", analyze_task_node)
    builder.add_node(
        "collect_initial_context",
        make_collect_context_node(monitoring, code, logs, timeout=timeout),
    )
    builder.add_node("correlate", make_correlate_node(code, timeout=timeout))
    builder.add_node("select_tool", make_select_tool_node(planner, registry, guardrails))
    builder.add_node("execute_tool", make_execute_tool_node(registry, guardrails))
    builder.add_node("evaluate_observation", evaluate_observation_node)
    builder.add_node("generate_analysis", make_build_analysis_node(model))
    builder.add_node("insufficient_context", insufficient_context_node)
    builder.add_node("final_response", finalize_node)

    builder.add_edge(START, "analyze_task")
    builder.add_edge("analyze_task", "collect_initial_context")
    builder.add_conditional_edges(
        "collect_initial_context",
        has_enough_context,
        {"correlate": "correlate", "insufficient_context": "insufficient_context"},
    )
    builder.add_edge("correlate", "select_tool")
    builder.add_conditional_edges(
        "select_tool",
        route_after_selection,
        {"execute_tool": "execute_tool", "generate_analysis": "generate_analysis"},
    )
    builder.add_edge("execute_tool", "evaluate_observation")
    builder.add_conditional_edges(
        "evaluate_observation",
        make_route_after_evaluation(guardrails),
        {"select_tool": "select_tool", "generate_analysis": "generate_analysis"},
    )
    builder.add_edge("generate_analysis", "final_response")
    builder.add_edge("final_response", END)
    builder.add_edge("insufficient_context", END)

    return builder.compile()
