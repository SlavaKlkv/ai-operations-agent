"""Shared fixtures. Visible to every test package below ``tests/``."""

from __future__ import annotations

import uuid

import pytest

from app.adapters.mock.dataset import BILLING_5XX
from app.adapters.mock.providers import (
    MockCodeProvider,
    MockLogProvider,
    MockMonitoringProvider,
)
from app.agent.state import initial_state

TASK = "После последнего релиза billing-service резко выросло количество 5xx. Разберись."


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No test may reach a real model provider.

    Without this, a developer with ANTHROPIC_API_KEY exported would silently
    run the suite against a paid API — slowly, nondeterministically, and with
    results that differ from CI. Tests that want a model inject a scripted one.
    """
    from app.core.config import get_settings

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    # Spawning four MCP subprocesses per app fixture would make the suite slow
    # for no gain: the integration layer has its own tests, which connect a
    # real client to a real server in-process.
    monkeypatch.setenv("MCP_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def scenario():
    return BILLING_5XX


@pytest.fixture
def monitoring(scenario):
    return MockMonitoringProvider(scenario)


@pytest.fixture
def code(scenario):
    return MockCodeProvider(scenario)


@pytest.fixture
def logs(scenario):
    return MockLogProvider(scenario)


@pytest.fixture
def fresh_state():
    return initial_state(str(uuid.uuid4()), TASK)


@pytest.fixture
async def db_session():
    """A throwaway SQLite database per test.

    The schema is created from the models rather than by running migrations:
    tests should fail when the *code* is wrong, not when a migration is merely
    unapplied. A separate migration test guards the two staying in sync.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.base import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(db_session):
    """HTTP client with the database dependency pointed at SQLite."""
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    from app.db.base import get_session
    from app.main import create_app

    async def override_session():
        yield db_session

    app = create_app()
    app.dependency_overrides[get_session] = override_session

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http
