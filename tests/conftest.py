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
