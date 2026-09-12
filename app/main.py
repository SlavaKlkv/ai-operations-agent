"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.routes import health, runs
from app.core.config import get_settings
from app.core.logging import configure_logging

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(get_settings().log_level)
    log.info("application.start", environment=get_settings().app_env)
    yield
    log.info("application.stop")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Operations Agent",
        version="0.1.0",
        summary="Agentic incident analysis with human-approved write actions.",
        description=(
            "Investigates backend incidents by correlating deployments, metrics, logs and "
            "code changes, then proposes an action that a human must approve."
        ),
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(runs.router)
    return app


app = create_app()
