"""Which MCP servers this deployment talks to, and on what terms.

Server configuration is code, not model input. A run cannot add a server, and
cannot widen what an existing server is allowed to do — the only direction
these settings move at runtime is narrower.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to type checkers
    from mcp.server.mcpserver import MCPServer


class Transport(StrEnum):
    #: Launch the server as a subprocess and speak over its stdin/stdout.
    STDIO = "stdio"
    #: Connect to an already-running server over HTTP.
    HTTP = "http"
    #: Run the server object inside this process, still over the protocol.
    #:
    #: Not a shortcut past MCP: the same client, the same JSON-RPC, the same
    #: tool discovery and annotations — only the transport differs. It exists
    #: because spawning four subprocesses per test is slow enough to discourage
    #: testing the integration layer at all, and an untested integration layer
    #: is the one that breaks.
    IN_PROCESS = "in_process"


@dataclass(frozen=True, slots=True)
class ServerSpec:
    """One MCP server this agent may connect to."""

    name: str
    transport: Transport
    #: For stdio: the command and arguments to launch.
    command: tuple[str, ...] = ()
    #: For HTTP: the endpoint URL.
    url: str | None = None
    #: For IN_PROCESS: a factory returning the server object to connect to.
    factory: Callable[[], MCPServer] | None = None
    env: dict[str, str] = field(default_factory=dict)
    #: Tools this deployment accepts from the server. Empty means "all the
    #: server offers"; a non-empty set is an allowlist enforced on discovery,
    #: so a server that grows a new tool cannot silently gain reach.
    allowed_tools: frozenset[str] = frozenset()
    #: Seconds to wait for one call before giving up on this server.
    timeout_seconds: float = 15.0
    #: Whether the run can proceed without this server. A monitoring server is
    #: load-bearing; a knowledge server is not.
    required: bool = True

    def permits(self, tool_name: str) -> bool:
        return not self.allowed_tools or tool_name in self.allowed_tools


def _stdio(module: str, **kwargs) -> ServerSpec:
    """A server launched from this repository, using the running interpreter.

    ``sys.executable`` rather than a bare ``python`` so a virtualenv, a
    container and a developer's shell all resolve to the same interpreter.
    """
    return ServerSpec(
        name=kwargs.pop("name"),
        transport=Transport.STDIO,
        command=(sys.executable, "-m", module),
        **kwargs,
    )


def default_servers() -> tuple[ServerSpec, ...]:
    """The four servers the agent ships with.

    They are separate processes because they stand in for four separate
    systems. Merging them would make the deployment simpler and the
    architecture a lie: in production, monitoring and the issue tracker are
    not the same vendor, do not fail together, and do not deserve the same
    permissions.
    """
    return (
        _stdio(
            "app.mcp_servers.monitoring",
            name="monitoring",
            allowed_tools=frozenset(
                {"get_service_metrics", "get_error_rate", "get_recent_alerts", "get_error_groups"}
            ),
        ),
        _stdio(
            "app.mcp_servers.code",
            name="code",
            allowed_tools=frozenset({"get_recent_deployments", "get_commits", "get_pull_request"}),
        ),
        _stdio(
            "app.mcp_servers.incident",
            name="incident",
            allowed_tools=frozenset(
                {"search_issues", "get_issue", "create_issue", "add_issue_comment"}
            ),
        ),
        _stdio(
            "app.mcp_servers.knowledge",
            name="knowledge",
            allowed_tools=frozenset({"search_runbooks", "get_runbook"}),
            # An investigation without a runbook is worse, not impossible.
            required=False,
        ),
    )
