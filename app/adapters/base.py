"""Provider protocols separating the agent from concrete data sources.

The graph never talks to Prometheus, GitHub or a log store directly. It talks
to these protocols, which are implemented by mock providers (development,
tests, evaluation) and later by MCP-backed providers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.models import (
    Alert,
    Commit,
    Deployment,
    ErrorGroup,
    MetricSeries,
    PullRequest,
)


@runtime_checkable
class MonitoringProvider(Protocol):
    async def get_service_metrics(
        self, service: str, metric: str, start: datetime, end: datetime
    ) -> MetricSeries: ...

    async def get_recent_alerts(
        self, service: str, start: datetime, end: datetime
    ) -> list[Alert]: ...


@runtime_checkable
class CodeProvider(Protocol):
    async def get_recent_deployments(
        self, service: str, start: datetime, end: datetime
    ) -> list[Deployment]: ...

    async def get_commits(self, service: str, since: datetime, until: datetime) -> list[Commit]: ...

    async def get_pull_request(self, service: str, number: int) -> PullRequest | None: ...


@runtime_checkable
class LogProvider(Protocol):
    async def get_error_groups(
        self, service: str, start: datetime, end: datetime, min_count: int = 1
    ) -> list[ErrorGroup]: ...
