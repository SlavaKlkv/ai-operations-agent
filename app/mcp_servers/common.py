"""Shared helpers for the MCP servers in this repository.

Kept small on purpose. These servers stand in for four different external
systems, and sharing anything beyond timestamp handling and error shape would
quietly couple systems that in reality know nothing about each other.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from mcp.server.mcpserver.exceptions import ToolError

from app.adapters.mock.dataset import DEFAULT_SCENARIO, SCENARIOS, Scenario


class ToolFailure(ToolError):
    """A tool could not do what was asked, for a reason worth telling the caller.

    Subclassing the SDK's :class:`~mcp.server.mcpserver.exceptions.ToolError`
    is what makes the message survive the protocol boundary: an anticipated
    failure comes back as ``is_error`` with the text intact, while anything
    else is treated as a crash and the caller is told only the tool name. The
    difference between "that service does not exist" and "the server fell
    over" is exactly what the agent needs in order to route.
    """


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def parse_window(start: str, end: str) -> tuple[datetime, datetime]:
    """Parse and sanity-check an ISO 8601 window.

    Servers validate their own inputs. The agent already validates arguments
    before sending them, but an MCP server is a public interface — anything
    that speaks the protocol can call it, so it cannot rely on a well-behaved
    client.
    """
    try:
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(end)
    except ValueError as exc:
        raise ToolFailure(f"timestamps must be ISO 8601: {exc}") from exc
    first = first if first.tzinfo else first.replace(tzinfo=UTC)
    last = last if last.tzinfo else last.replace(tzinfo=UTC)
    if last < first:
        raise ToolFailure("end must not be earlier than start")
    return first, last


def services_in(scenario: Scenario) -> list[str]:
    return sorted({service for service, _ in scenario.metrics})


def scenario_from_env() -> Scenario:
    """Which synthetic world this server process serves.

    A single environment variable is the whole configuration surface: these
    servers exist to be swapped for real backends, so anything more elaborate
    would be configuring something that is going to be deleted.
    """
    name = os.environ.get("MCP_SCENARIO", "")
    return SCENARIOS.get(name, DEFAULT_SCENARIO)
