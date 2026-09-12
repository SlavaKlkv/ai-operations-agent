"""The single door between a decision to call a tool and the tool running.

Nothing in the graph calls a provider directly. A tool request — wherever it
came from, an LLM or deterministic code — arrives here as a name and a dict,
and leaves as a validated, timed, budgeted, audited invocation.

The order of operations is the design: policy first, then argument validation,
then execution under a timeout, then result validation. A request that fails an
early check never reaches the provider, and the failure is returned as data the
graph can route on rather than raised through the workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from app.agent.guardrails import Guardrails, GuardrailViolation, call_signature
from app.agent.state import ToolCallRecord
from app.agent.tooling import call_tool
from app.agent.tools.base import (
    AgentTool,
    InvalidToolArgumentsError,
    ToolError,
    ToolRegistry,
    UnknownToolError,
)


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """What the planner decided to do, before anyone has checked whether it may."""

    tool: str
    arguments: dict[str, Any]
    #: Why the planner wants this. Kept for the audit trail and evaluation.
    reason: str = ""

    @property
    def signature(self) -> str:
        return call_signature(self.tool, self.arguments)


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """The outcome, in the three shapes the system needs it in.

    ``result`` is the typed object the graph reasons over, ``digest`` is the
    bounded text the model is allowed to read, and ``record`` is the audit row.
    Keeping them distinct is what stops raw provider output leaking into a
    prompt by accident.
    """

    request: ToolRequest
    record: ToolCallRecord
    result: BaseModel | None = None
    digest: str = ""

    @property
    def ok(self) -> bool:
        return self.record.ok

    @property
    def error(self) -> str | None:
        return self.record.error


class ToolExecutor:
    """Registry + policy + timing, bound together for the lifetime of a run."""

    def __init__(self, registry: ToolRegistry, guardrails: Guardrails) -> None:
        self._registry = registry
        self._guardrails = guardrails
        self._history: list[str] = []

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def guardrails(self) -> Guardrails:
        return self._guardrails

    @property
    def history(self) -> tuple[str, ...]:
        """Signatures of everything attempted, in order."""
        return tuple(self._history)

    def available(self) -> tuple[AgentTool[Any, Any], ...]:
        return self._guardrails.available(self._registry)

    def authorise(self, request: ToolRequest) -> AgentTool[Any, Any]:
        """Run every policy check. Raises rather than returning a verdict, so a
        caller cannot accidentally ignore a refusal."""
        tool = self._registry.get(request.tool)
        self._guardrails.check_tool(tool)
        self._guardrails.check_repetition(request.signature, self._history)
        return tool

    async def execute(
        self,
        request: ToolRequest,
        *,
        defaults: dict[str, Any] | None = None,
    ) -> ToolInvocation:
        """Authorise, validate, run and record one tool call.

        ``defaults`` fill arguments the planner left out — in practice the
        investigation's time window. They are applied before validation and
        never override what the planner supplied explicitly.
        """
        try:
            tool = self._registry.get(request.tool)
        except UnknownToolError as exc:
            return self._refused(request, exc)

        arguments = _merge_defaults(request.arguments, defaults, tool.args_schema)
        request = ToolRequest(tool=request.tool, arguments=arguments, reason=request.reason)

        try:
            self.authorise(request)
        except (UnknownToolError, GuardrailViolation, ToolError) as exc:
            return self._refused(request, exc)

        self._history.append(request.signature)

        try:
            parsed = tool.parse_arguments(arguments)
        except InvalidToolArgumentsError as exc:
            return self._refused(request, exc)

        outcome = await call_tool(
            tool.name,
            lambda: tool.handler(parsed),
            arguments=_jsonable(arguments),
            timeout=self._guardrails.tool_timeout_seconds,
            retries=self._guardrails.tool_retries,
        )
        if outcome.value is None:
            return ToolInvocation(request=request, record=outcome.record)

        try:
            validated = tool.parse_result(outcome.value)
        except ToolError as exc:
            return self._refused(request, exc, duration_ms=outcome.record.duration_ms)

        digest = tool.digest(validated)
        record = outcome.record.model_copy(update={"result_summary": digest[:500]})
        return ToolInvocation(request=request, record=record, result=validated, digest=digest)

    def _refused(
        self, request: ToolRequest, exc: Exception, *, duration_ms: float = 0.0
    ) -> ToolInvocation:
        """A refusal is still a recorded tool call — the audit trail must show
        what the agent tried to do, not only what it was allowed to do."""
        return ToolInvocation(
            request=request,
            record=ToolCallRecord(
                tool=request.tool,
                arguments=_jsonable(request.arguments),
                started_at=datetime.now(UTC),
                duration_ms=duration_ms,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            ),
        )


def _merge_defaults(
    arguments: dict[str, Any],
    defaults: dict[str, Any] | None,
    args_schema: type[BaseModel],
) -> dict[str, Any]:
    """Fill omitted arguments, but only ones this tool actually declares.

    Filtering by the schema matters: the window defaults are offered to every
    call, and a tool that takes no window (``get_pull_request``) must not be
    handed one — its schema forbids extra fields and would reject the call.
    """
    merged = dict(arguments)
    if not defaults:
        return merged
    for key, value in defaults.items():
        if key in args_schema.model_fields and merged.get(key) is None:
            merged[key] = value
    return merged


def _jsonable(arguments: dict[str, Any]) -> dict[str, Any]:
    """Arguments are stored in JSON columns, so datetimes become strings here."""
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in arguments.items()
    }
