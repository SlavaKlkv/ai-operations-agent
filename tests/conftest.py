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
    from app.api.routes.runs import get_graph
    from app.core.config import get_settings

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    # Spawning four MCP subprocesses per app fixture would make the suite slow
    # for no gain: the integration layer has its own tests, which connect a
    # real client to a real server in-process.
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setenv("CHECKPOINTER", "memory")
    monkeypatch.setenv("CACHE_ENABLED", "false")
    get_settings.cache_clear()
    # The API compiles one graph per process and caches it. That graph holds
    # the mock issue tracker, whose contents would otherwise leak from one
    # test into the next — a duplicate-title refusal in an unrelated test.
    get_graph.cache_clear()
    yield
    get_settings.cache_clear()
    get_graph.cache_clear()


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

    # Importing the models is what populates Base.metadata. Relying on some
    # other module to have imported them first makes table creation depend on
    # test collection order, which is how this fixture silently produced an
    # empty database.
    import app.db.models  # noqa: F401
    from app.db.base import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _issue_token(session, email: str, *, can_approve: bool) -> str:
    """Create a user and return their bearer token."""
    from app.api.security import issue_token
    from app.db.models import User

    token, digest = issue_token()
    session.add(
        User(
            email=email,
            display_name=email.split("@")[0],
            can_approve=can_approve,
            api_token_hash=digest,
        )
    )
    await session.commit()
    return token


@pytest.fixture
async def approver_token(db_session):
    return await _issue_token(db_session, "oncall@example.com", can_approve=True)


@pytest.fixture
async def reader_token(db_session):
    """Someone who can investigate but not authorise a change."""
    return await _issue_token(db_session, "viewer@example.com", can_approve=False)


@pytest.fixture
async def app(db_session):
    """The application, with the database pointed at the throwaway SQLite."""
    from app.db.base import get_session
    from app.main import create_app

    async def override_session():
        yield db_session

    built = create_app()
    built.dependency_overrides[get_session] = override_session
    return built


@pytest.fixture
async def http_client(app):
    """An unauthenticated client. Most tests want ``client`` instead."""
    from asgi_lifespan import LifespanManager
    from httpx import ASGITransport, AsyncClient

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as built:
            yield built


@pytest.fixture
async def client(http_client, approver_token):
    """The default client: authenticated, and allowed to approve writes."""
    http_client.headers["authorization"] = f"Bearer {approver_token}"
    return http_client


@pytest.fixture
async def reader_client(http_client, reader_token):
    http_client.headers["authorization"] = f"Bearer {reader_token}"
    return http_client
