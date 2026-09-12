"""Turn a free-form request into a bounded, typed investigation plan.

V1 does this deterministically: a regex over known service names plus explicit
defaults. Deterministic code is preferred wherever the answer does not actually
require language understanding — the LLM-backed variant arrives in V2 and must
produce the same :class:`TaskAnalysis` shape.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field

from app.agent.state import AgentState
from app.adapters.mock.dataset import DEFAULT_SCENARIO

_SERVICE_RE = re.compile(r"\b([a-z0-9]+(?:-[a-z0-9]+)*-service)\b", re.IGNORECASE)
DEFAULT_LOOKBACK = timedelta(hours=1)


class TaskAnalysis(BaseModel):
    """Structured reading of the user's request."""

    model_config = ConfigDict(extra="forbid")

    target_service: str | None = None
    window_start: datetime
    window_end: datetime
    keywords: list[str] = Field(default_factory=list)


def extract_service(task: str) -> str | None:
    match = _SERVICE_RE.search(task)
    return match.group(1).lower() if match else None


def analyse_task(task: str, now: datetime | None = None) -> TaskAnalysis:
    reference = now or _scenario_now()
    return TaskAnalysis(
        target_service=extract_service(task),
        window_start=reference - DEFAULT_LOOKBACK,
        window_end=reference,
        keywords=sorted({w.lower() for w in re.findall(r"\b(5xx|4xx|latency|errors?|timeout)\b", task, re.I)}),
    )


def _scenario_now() -> datetime:
    """Anchor the window to the synthetic world while real clocks are absent."""
    latest = max(
        (p.timestamp for series in DEFAULT_SCENARIO.metrics.values() for p in series.points),
        default=datetime.now(UTC),
    )
    return latest


async def analyze_task_node(state: AgentState) -> AgentState:
    analysis = analyse_task(state["task"])
    service = state.get("target_service") or analysis.target_service
    return AgentState(
        target_service=service,
        window_start=analysis.window_start,
        window_end=analysis.window_end,
        current_step="analyze_task",
        step_count=state.get("step_count", 0) + 1,
        observations=[
            {
                "node": "analyze_task",
                "target_service": service,
                "window": [analysis.window_start.isoformat(), analysis.window_end.isoformat()],
                "keywords": analysis.keywords,
            }
        ],
    )
