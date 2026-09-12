"""Liveness endpoint. Intentionally dependency-free so it stays green while
PostgreSQL or an MCP server is down — readiness is a separate concern."""

from __future__ import annotations

from fastapi import APIRouter

from app.agent import checkpointing
from app.api.schemas import HealthResponse
from app.core.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version="0.1.0",
        environment=settings.app_env,
        # Surfaced because it changes a guarantee the API makes: without a
        # durable checkpointer, a run awaiting approval is lost on restart.
        durable_approvals=checkpointing.is_durable(),
        authentication=settings.auth_enabled,
    )
