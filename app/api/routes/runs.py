"""Agent run endpoints."""

from __future__ import annotations

import uuid
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import build_graph
from app.agent.state import initial_state
from app.api.schemas import RunDetail, RunRequest, RunSummary, ToolCallView
from app.db.base import get_session
from app.db.models import AgentRun
from app.domain.models import IncidentAnalysis
from app.services import run_store

router = APIRouter(prefix="/runs", tags=["runs"])


@lru_cache(maxsize=1)
def get_graph():
    """Compile once per process.

    The graph holds no per-run state — nodes read and return state, and the
    tool executor is rebuilt from state on every call — so one compiled graph
    serves concurrent requests safely. Compiling per request would also mean
    re-reading credentials and rebuilding the registry on every investigation.
    """
    return build_graph()


def _to_detail(run: AgentRun) -> RunDetail:
    detail = RunDetail.model_validate(run)
    if run.analyses:
        detail.analysis = IncidentAnalysis.model_validate(run.analyses[-1].payload)
    detail.tool_calls = [
        ToolCallView.model_validate(tc) for tc in sorted(run.tool_calls, key=lambda t: t.started_at)
    ]
    return detail


@router.post("", response_model=RunDetail, status_code=status.HTTP_201_CREATED)
async def start_run(payload: RunRequest, session: AsyncSession = Depends(get_session)) -> RunDetail:
    """Start an investigation and return its terminal state.

    The run executes inline: V1 workflows finish in well under a second against
    mock providers, and a synchronous answer keeps the API honest about how
    long an investigation actually takes. Long-running variants move to Celery
    once real integrations make that true.
    """
    run = await run_store.create_run(
        session, task=payload.task, target_service=payload.target_service
    )
    final = await get_graph().ainvoke(
        initial_state(str(run.id), payload.task, payload.target_service)
    )
    await run_store.persist_final_state(session, run, final)
    stored = await run_store.get_run(session, run.id)
    assert stored is not None
    return _to_detail(stored)


@router.get("", response_model=list[RunSummary])
async def list_runs(
    limit: int = 50, session: AsyncSession = Depends(get_session)
) -> list[RunSummary]:
    runs = await run_store.list_runs(session, limit=min(limit, 200))
    return [RunSummary.model_validate(r) for r in runs]


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(run_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> RunDetail:
    run = await run_store.get_run(session, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run not found")
    return _to_detail(run)
