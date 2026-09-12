"""Graph-level tests: routing decisions and a full deterministic run."""

from __future__ import annotations

from app.adapters.mock.dataset import INCIDENT_START
from app.agent.graph import build_graph, has_enough_context
from app.agent.state import CollectedContext, RunStatus, initial_state
from app.domain.models import MetricSeries


def test_routing_requires_metrics():
    assert has_enough_context({"context": CollectedContext()}) == "insufficient_context"
    assert has_enough_context({}) == "insufficient_context"


def test_routing_short_circuits_on_failure():
    context = CollectedContext(
        metrics={
            "error_rate": MetricSeries(service="s", metric="error_rate", unit="ratio", points=())
        }
    )
    assert has_enough_context({"context": context}) == "correlate"
    assert (
        has_enough_context({"context": context, "status": RunStatus.FAILED})
        == "insufficient_context"
    )


async def test_full_run_identifies_the_release(monitoring, code, logs, fresh_state):
    graph = build_graph(monitoring=monitoring, code=code, logs=logs)
    final = await graph.ainvoke(fresh_state)

    assert final["status"] is RunStatus.COMPLETED
    assert final["current_step"] == "final_response"
    analysis = final["analysis"]
    assert analysis.service == "billing-service"
    assert analysis.incident_start == INCIDENT_START
    assert "v1.8.4" in analysis.suspected_causes[0].statement
    assert analysis.confidence >= 0.8
    assert analysis.requires_human_review is True


async def test_every_claim_is_backed_by_a_tool_call(monitoring, code, logs, fresh_state):
    """Evidence grounding: no evidence item may cite a tool that never ran."""
    graph = build_graph(monitoring=monitoring, code=code, logs=logs)
    final = await graph.ainvoke(fresh_state)

    executed = {r.tool for r in final["tool_calls"]} | {"detect_spike"}
    cited = {e.source_tool for e in final["analysis"].evidence}
    assert cited <= executed


async def test_run_stays_within_its_budget(monitoring, code, logs, fresh_state):
    graph = build_graph(monitoring=monitoring, code=code, logs=logs)
    final = await graph.ainvoke(fresh_state)
    assert final["tool_call_count"] <= 12
    assert final["step_count"] <= 30


async def test_unknown_service_ends_in_a_stated_failure(monitoring, code, logs):
    graph = build_graph(monitoring=monitoring, code=code, logs=logs)
    final = await graph.ainvoke(initial_state("r1", "что-то не так с payments-service"))

    assert final["status"] is RunStatus.FAILED
    assert final["current_step"] == "insufficient_context"
    assert "stopped before analysis" in final["final_result"]
    assert final["analysis"] is None


async def test_failure_path_records_why(monitoring, code, logs):
    graph = build_graph(monitoring=monitoring, code=code, logs=logs)
    final = await graph.ainvoke(initial_state("r2", "no service named here"))
    assert final["errors"]
    assert final["errors"][0].kind == "insufficient_input"
