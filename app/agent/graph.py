"""Graph assembly.

V1 is a deterministic pipeline with one conditional edge: whether the collected
context is worth analysing at all. The point of starting here is that state,
routing and termination are already real before an LLM is allowed to pick the
next step — later versions add choice, not structure.

    START → analyze_task → collect_initial_context → ┬→ correlate → generate_analysis → END
                                                     └→ insufficient_context → END
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.adapters.base import CodeProvider, LogProvider, MonitoringProvider
from app.adapters.mock.providers import (
    MockCodeProvider,
    MockLogProvider,
    MockMonitoringProvider,
)
from app.agent.nodes.analyze_task import analyze_task_node
from app.agent.nodes.build_analysis import build_analysis_node
from app.agent.nodes.collect_context import make_collect_context_node
from app.agent.nodes.correlate import make_correlate_node
from app.agent.state import AgentState, RunStatus


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
    timeout: float = 15.0,
):
    """Compile the workflow. Providers are injected so tests can substitute them."""
    monitoring = monitoring or MockMonitoringProvider()
    code = code or MockCodeProvider()
    logs = logs or MockLogProvider()

    builder = StateGraph(AgentState)
    builder.add_node("analyze_task", analyze_task_node)
    builder.add_node(
        "collect_initial_context",
        make_collect_context_node(monitoring, code, logs, timeout=timeout),
    )
    builder.add_node("correlate", make_correlate_node(code, timeout=timeout))
    builder.add_node("generate_analysis", build_analysis_node)
    builder.add_node("insufficient_context", insufficient_context_node)
    builder.add_node("final_response", finalize_node)

    builder.add_edge(START, "analyze_task")
    builder.add_edge("analyze_task", "collect_initial_context")
    builder.add_conditional_edges(
        "collect_initial_context",
        has_enough_context,
        {"correlate": "correlate", "insufficient_context": "insufficient_context"},
    )
    builder.add_edge("correlate", "generate_analysis")
    builder.add_edge("generate_analysis", "final_response")
    builder.add_edge("final_response", END)
    builder.add_edge("insufficient_context", END)

    return builder.compile()
