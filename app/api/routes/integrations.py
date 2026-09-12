"""Visibility into the integration layer.

An agent whose data comes from four external systems needs an answer to "which
of them is actually up, and what is it offering me" that does not require
running an investigation to find out. This endpoint is that answer, and it is
also how a reader of the repository sees that MCP is really being spoken:
the tool list here is discovered at runtime, not declared in code.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.mcp.client import MCPToolPool, RemoteTool, ServerStatus
from app.mcp.runtime import get_pool

router = APIRouter(prefix="/mcp", tags=["integrations"])


class ToolView(BaseModel):
    name: str
    server: str
    access: str
    description: str


class ServerView(BaseModel):
    name: str
    connected: bool
    required: bool
    tool_count: int
    error: str | None = None


class IntegrationsView(BaseModel):
    healthy: bool
    servers: list[ServerView] = Field(default_factory=list)
    tools: list[ToolView] = Field(default_factory=list)


def _server_view(server: ServerStatus) -> ServerView:
    return ServerView(
        name=server.name,
        connected=server.connected,
        required=server.required,
        tool_count=server.tool_count,
        error=server.error,
    )


def _tool_view(tool: RemoteTool) -> ToolView:
    return ToolView(
        name=tool.name,
        server=tool.server,
        access="read" if tool.read_only else "write",
        description=tool.description,
    )


@router.get(
    "/servers",
    response_model=IntegrationsView,
    summary="Connected MCP servers and the tools they advertise",
)
async def list_servers(
    response: Response, pool: MCPToolPool = Depends(get_pool)
) -> IntegrationsView:
    """Report the integration layer, and say so in the status code.

    A degraded integration layer returns 503 rather than a cheerful 200 with
    ``healthy: false`` buried in the body — this endpoint is meant to be
    usable as a readiness probe, and a probe that always succeeds is not one.
    """
    await pool.connect()
    if not pool.healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return IntegrationsView(
        healthy=pool.healthy,
        servers=[_server_view(s) for s in pool.status],
        tools=sorted((_tool_view(t) for t in pool.tools()), key=lambda t: (t.server, t.name)),
    )
