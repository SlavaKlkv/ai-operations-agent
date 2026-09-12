"""Execution wrapper that every tool call in the graph goes through.

It exists so that timeouts, retries, and the audit record are properties of the
*runtime*, not of individual tools. A tool that forgets to handle a timeout is
still bounded; a tool that succeeds is still recorded.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.agent.state import ToolCallRecord


class ToolBudgetExceeded(RuntimeError):
    """Raised when a run tries to exceed its allowed number of tool calls."""


@dataclass(slots=True)
class ToolOutcome[T]:
    value: T | None
    record: ToolCallRecord

    @property
    def ok(self) -> bool:
        return self.record.ok


async def call_tool[T](
    name: str,
    fn: Callable[[], Awaitable[T]],
    *,
    arguments: dict[str, Any] | None = None,
    timeout: float = 15.0,
    retries: int = 1,
    summarise: Callable[[T], str] | None = None,
) -> ToolOutcome[T]:
    """Run ``fn`` under a timeout, retrying transient failures.

    ``retries`` counts *additional* attempts after the first one. The returned
    record always describes the final attempt, and ``attempt`` says how many
    were needed — evaluation uses that to spot flaky or misused tools.
    """
    arguments = arguments or {}
    last_error: str | None = None
    started = datetime.now(UTC)

    for attempt in range(1, retries + 2):
        t0 = time.perf_counter()
        try:
            value = await asyncio.wait_for(fn(), timeout=timeout)
        except TimeoutError:
            last_error = f"timeout after {timeout}s"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            return ToolOutcome(
                value=value,
                record=ToolCallRecord(
                    tool=name,
                    arguments=arguments,
                    started_at=started,
                    duration_ms=round((time.perf_counter() - t0) * 1000, 3),
                    ok=True,
                    result_summary=summarise(value) if summarise else "",
                    attempt=attempt,
                ),
            )

    return ToolOutcome(
        value=None,
        record=ToolCallRecord(
            tool=name,
            arguments=arguments,
            started_at=started,
            duration_ms=round((time.perf_counter() - t0) * 1000, 3),
            ok=False,
            error=last_error,
            attempt=retries + 1,
        ),
    )
