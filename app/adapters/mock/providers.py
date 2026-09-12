"""Mock implementations of the provider protocols backed by a Scenario."""

from __future__ import annotations

from datetime import datetime

from app.adapters.mock.dataset import DEFAULT_SCENARIO, Scenario, aggregate_logs
from app.domain.models import (
    Alert,
    Commit,
    Deployment,
    ErrorGroup,
    MetricSeries,
    PullRequest,
)


class UnknownMetricError(LookupError):
    """Raised when a scenario has no series for the requested service/metric."""


class MockMonitoringProvider:
    def __init__(self, scenario: Scenario = DEFAULT_SCENARIO) -> None:
        self._scenario = scenario

    async def get_service_metrics(
        self, service: str, metric: str, start: datetime, end: datetime
    ) -> MetricSeries:
        series = self._scenario.metrics.get((service, metric))
        if series is None:
            raise UnknownMetricError(f"no series {metric!r} for service {service!r}")
        points = tuple(p for p in series.points if start <= p.timestamp <= end)
        return series.model_copy(update={"points": points})

    async def get_recent_alerts(self, service: str, start: datetime, end: datetime) -> list[Alert]:
        return [
            a for a in self._scenario.alerts if a.service == service and start <= a.fired_at <= end
        ]


class MockCodeProvider:
    def __init__(self, scenario: Scenario = DEFAULT_SCENARIO) -> None:
        self._scenario = scenario

    async def get_recent_deployments(
        self, service: str, start: datetime, end: datetime
    ) -> list[Deployment]:
        found = [
            d
            for d in self._scenario.deployments
            if d.service == service and start <= d.deployed_at <= end
        ]
        return sorted(found, key=lambda d: d.deployed_at, reverse=True)

    async def get_commits(self, service: str, since: datetime, until: datetime) -> list[Commit]:
        del service  # the synthetic world holds one repository per scenario
        found = [c for c in self._scenario.commits if since <= c.committed_at <= until]
        return sorted(found, key=lambda c: c.committed_at, reverse=True)

    async def get_pull_request(self, service: str, number: int) -> PullRequest | None:
        del service
        return next((pr for pr in self._scenario.pull_requests if pr.number == number), None)


class MockLogProvider:
    def __init__(self, scenario: Scenario = DEFAULT_SCENARIO) -> None:
        self._scenario = scenario

    async def get_error_groups(
        self, service: str, start: datetime, end: datetime, min_count: int = 1
    ) -> list[ErrorGroup]:
        logs = [e for e in self._scenario.logs if e.service == service]
        return aggregate_logs(logs, start, end, min_count)
