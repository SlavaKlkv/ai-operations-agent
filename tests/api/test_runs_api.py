"""API-level tests: the HTTP contract and what actually lands in the database."""

from __future__ import annotations

import uuid

TASK = "После последнего релиза billing-service резко выросло количество 5xx. Разберись."


async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_start_run_returns_the_analysis(client):
    response = await client.post("/runs", json={"task": TASK})
    assert response.status_code == 201

    body = response.json()
    assert body["status"] == "completed"
    assert body["target_service"] == "billing-service"
    assert body["analysis"]["service"] == "billing-service"
    assert "v1.8.4" in body["analysis"]["suspected_causes"][0]["statement"]
    assert body["analysis"]["requires_human_review"] is True


async def test_tool_calls_are_persisted_for_audit(client):
    body = (await client.post("/runs", json={"task": TASK})).json()
    tools = [tc["tool"] for tc in body["tool_calls"]]
    assert "get_service_metrics" in tools
    assert "get_recent_deployments" in tools
    assert all(tc["ok"] for tc in body["tool_calls"])
    assert body["tool_call_count"] == len(body["tool_calls"])


async def test_run_can_be_fetched_again(client):
    created = (await client.post("/runs", json={"task": TASK})).json()
    fetched = (await client.get(f"/runs/{created['id']}")).json()
    assert fetched["id"] == created["id"]
    assert fetched["analysis"]["summary"] == created["analysis"]["summary"]


async def test_listing_runs(client):
    await client.post("/runs", json={"task": TASK})
    await client.post("/runs", json={"task": TASK})
    runs = (await client.get("/runs")).json()
    assert len(runs) == 2
    assert {r["status"] for r in runs} == {"completed"}


async def test_unknown_run_is_404(client):
    assert (await client.get(f"/runs/{uuid.uuid4()}")).status_code == 404


async def test_task_validation_rejects_junk(client):
    assert (await client.post("/runs", json={"task": "hi"})).status_code == 422
    assert (await client.post("/runs", json={"task": TASK, "nope": 1})).status_code == 422


async def test_failed_run_is_persisted_with_its_reason(client):
    body = (await client.post("/runs", json={"task": "что-то сломалось, непонятно где"})).json()
    assert body["status"] == "failed"
    assert body["analysis"] is None
    assert "stopped before analysis" in body["final_result"]
