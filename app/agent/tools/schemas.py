"""Argument and result schemas for every tool.

Two rules shape these models.

*Arguments* are as small as they can be. The time window is optional on every
query tool: if the model omits it, the executor injects the window the task
analysis resolved. That is deliberate — a model that has to invent timestamps
will invent them, and an investigation anchored to a hallucinated window is
worse than one anchored to a slightly wrong default.

*Results* are typed domain objects, not prose. The graph keeps them; the model
sees only what the tool's ``render`` function produces.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import (
    Alert,
    Commit,
    Deployment,
    ErrorGroup,
    MetricSeries,
    PullRequest,
)

#: The metrics the monitoring layer is guaranteed to expose. Constraining this
#: to a literal means an invented metric name fails validation instead of
#: reaching the provider and coming back as an opaque lookup error.
MetricName = Literal["error_rate", "request_rate", "latency_p50", "latency_p95", "latency_p99"]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Result(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WindowArgs(_Args):
    """Shared optional window. Omit both to use the investigation's window."""

    start: datetime | None = Field(
        default=None, description="Inclusive start (ISO 8601). Omit to use the incident window."
    )
    end: datetime | None = Field(
        default=None, description="Inclusive end (ISO 8601). Omit to use the incident window."
    )


# ── Monitoring ───────────────────────────────────────────────────────────────


class GetServiceMetricsArgs(WindowArgs):
    service: str = Field(description="Service name, e.g. 'billing-service'.")
    metric: MetricName = Field(description="Which time series to fetch.")


class MetricsResult(_Result):
    series: MetricSeries


class GetRecentAlertsArgs(WindowArgs):
    service: str = Field(description="Service whose alerts to list.")


class AlertsResult(_Result):
    alerts: tuple[Alert, ...] = ()


# ── Code and deployments ─────────────────────────────────────────────────────


class GetRecentDeploymentsArgs(WindowArgs):
    service: str = Field(description="Service whose releases to list, newest first.")


class DeploymentsResult(_Result):
    deployments: tuple[Deployment, ...] = ()


class GetCommitsArgs(WindowArgs):
    service: str = Field(description="Service whose repository to read.")


class CommitsResult(_Result):
    commits: tuple[Commit, ...] = ()


class GetPullRequestArgs(_Args):
    service: str = Field(description="Service whose repository holds the pull request.")
    number: int = Field(gt=0, description="Pull request number.")


class PullRequestResult(_Result):
    pull_request: PullRequest | None = None


# ── Logs ─────────────────────────────────────────────────────────────────────


class GetErrorGroupsArgs(WindowArgs):
    service: str = Field(description="Service whose errors to aggregate.")
    min_count: int = Field(
        default=1, ge=1, le=10_000, description="Drop groups with fewer occurrences than this."
    )


class ErrorGroupsResult(_Result):
    groups: tuple[ErrorGroup, ...] = ()
