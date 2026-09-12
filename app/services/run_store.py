"""Persistence for agent runs: turning terminal graph state into rows."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.state import AgentState, RunStatus
from app.db.base import utcnow
from app.db.models import AgentRun, AuditEvent, IncidentAnalysisRecord, ToolCall


async def create_run(
    session: AsyncSession, *, task: str, target_service: str | None = None
) -> AgentRun:
    run = AgentRun(
        task=task,
        target_service=target_service,
        status=RunStatus.RUNNING,
        started_at=utcnow(),
    )
    session.add(run)
    await session.flush()
    session.add(
        AuditEvent(
            run_id=run.id, at=utcnow(), actor="system", action="run.created", detail={"task": task}
        )
    )
    await session.commit()
    return run


async def persist_final_state(session: AsyncSession, run: AgentRun, state: AgentState) -> AgentRun:
    """Write everything the run produced, in one transaction."""
    run.status = state.get("status", RunStatus.COMPLETED)
    run.approval_state = state.get("approval_state", run.approval_state)
    run.target_service = state.get("target_service") or run.target_service
    run.step_count = state.get("step_count", 0)
    run.tool_call_count = state.get("tool_call_count", 0)
    run.total_tokens = state.get("input_tokens", 0) + state.get("output_tokens", 0)
    run.final_result = state.get("final_result")
    run.finished_at = utcnow()
    run.state_snapshot = serialise_state(state)

    for record in state.get("tool_calls", []):
        session.add(
            ToolCall(
                run_id=run.id,
                tool=record.tool,
                arguments=record.arguments,
                started_at=record.started_at,
                duration_ms=record.duration_ms,
                attempt=record.attempt,
                ok=record.ok,
                error=record.error,
                result_summary=record.result_summary,
            )
        )

    analysis = state.get("analysis")
    if analysis is not None:
        session.add(
            IncidentAnalysisRecord(
                run_id=run.id,
                service=analysis.service,
                incident_start=analysis.incident_start,
                confidence=analysis.confidence,
                summary=analysis.summary,
                payload=analysis.model_dump(mode="json"),
            )
        )

    session.add(
        AuditEvent(
            run_id=run.id,
            at=utcnow(),
            actor="agent",
            action="run.finished",
            detail={
                "status": str(run.status),
                "tool_calls": run.tool_call_count,
                "llm_calls": state.get("llm_calls", 0),
                "total_tokens": run.total_tokens,
            },
        )
    )
    await session.commit()
    return run


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> AgentRun | None:
    stmt = (
        select(AgentRun)
        .where(AgentRun.id == run_id)
        .options(
            selectinload(AgentRun.tool_calls),
            selectinload(AgentRun.analyses),
            selectinload(AgentRun.approvals),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_runs(session: AsyncSession, *, limit: int = 50) -> list[AgentRun]:
    stmt = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars())


def serialise_state(state: AgentState) -> dict:
    """JSON-safe snapshot of terminal state, used for replay and debugging."""

    def encode(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if isinstance(value, list):
            return [encode(v) for v in value]
        if isinstance(value, dict):
            return {k: encode(v) for k, v in value.items()}
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    return {key: encode(value) for key, value in state.items()}
