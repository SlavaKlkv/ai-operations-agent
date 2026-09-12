"""The application's single MCP pool, tied to the process lifetime.

One pool per process, opened at startup and closed at shutdown. The reason is
cost: each stdio server is a subprocess, and opening four of them per
investigation would be most of a run's latency. The reason it is safe is that
the pool owns its own connections in a dedicated task — see
:meth:`app.mcp.client.MCPToolPool.connect`.

Tests and the evaluation harness build their own pools and never touch this
module, which is why the graph takes providers rather than reaching for a
global.
"""

from __future__ import annotations

from app.mcp.client import MCPToolPool
from app.mcp.config import ServerSpec

_pool: MCPToolPool | None = None


async def startup(specs: tuple[ServerSpec, ...] | None = None) -> MCPToolPool:
    """Open the pool. Safe to call twice; the second call is a no-op."""
    global _pool
    if _pool is None:
        _pool = MCPToolPool(specs)
        await _pool.connect()
    return _pool


async def shutdown() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


def get_pool() -> MCPToolPool:
    """FastAPI dependency. Creating the pool lazily here rather than raising
    keeps a request from failing merely because startup ordering changed."""
    global _pool
    if _pool is None:
        _pool = MCPToolPool()
    return _pool
