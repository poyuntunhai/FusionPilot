"""
Expose the platform's tools as MCP tools, in-process.

Each tool's implementation already lives in ``domain_tools``; this module only registers it with an
MCP server and binds the per-turn context the implementation needs. The server is rebuilt per tool
call, which is what makes that binding possible without threading the context through the protocol
— the same choice the reference project makes, and cheap because nothing is spawned.

``description`` is taken from ``TOOL_CATALOG`` on purpose: the text the model sees and the text an
MCP client sees are the same text, so a tool cannot come to mean one thing in the loop and another
over the protocol.
"""

from __future__ import annotations

import functools
from typing import Any, Awaitable, Callable

from mcp.server import MCPServer

from ..domain_tools import (
    TOOL_CATALOG,
    ToolContext,
    ToolOutcome,
    _compare,
    _metrics,
    _run,
    _search_knowledge,
    _update_config,
    _validate,
)

_DESCRIPTION: dict[str, str] = {tool["name"]: tool["description"] for tool in TOOL_CATALOG}


def _guarded(handler: Callable[..., Awaitable[ToolOutcome]]) -> Callable[..., Awaitable[ToolOutcome]]:
    """
    Turn a tool crash into a failed outcome that still names the exception class.

    The loop distinguishes "the tool said no" from "the tool crashed", and it puts the exception
    class into the error it feeds back to the model. Left to itself MCP replaces that with a
    generic "raised an unexpected exception", which drops the only part worth reading — so the
    crash is caught here, where the class is still known.

    ``functools.wraps`` matters: the SDK derives each tool's input schema from the handler's
    signature, and the wrapper has to keep the wrapped signature visible or every tool would be
    advertised as taking no arguments.
    """
    @functools.wraps(handler)
    async def wrapper(*args: Any, **kwargs: Any) -> ToolOutcome:
        try:
            return await handler(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - a crash is reported, not propagated
            return ToolOutcome(ok=False, error=f"{type(exc).__name__}: {exc}")

    return wrapper


def build_tool_server(context: ToolContext, authorization: str | None) -> MCPServer:
    """A server whose tools read and write ``context``, authorised by ``authorization``."""
    server = MCPServer(
        name="fusionpilot-tools",
        title="FusionPilot 领域工具",
        description="雷达与电子对抗仿真的配置、校验、运行与解读工具。",
        instructions=(
            "修改配置前先读取当前配置；运行仿真会消耗资源，需要用户确认；"
            "所有数值都来自 Java 仿真核心，工具不产生任何指标。"
        ),
    )

    @server.tool(name="get_experiment_config", title="读取实验配置", description=_DESCRIPTION["get_experiment_config"])
    @_guarded
    async def get_experiment_config() -> ToolOutcome:
        return ToolOutcome(
            ok=True,
            summary={
                "working_config": context.working_config,
                "default_config": context.default_config,
            },
        )

    @server.tool(
        name="update_experiment_config",
        title="修改实验配置",
        description=_DESCRIPTION["update_experiment_config"],
    )
    @_guarded
    async def update_experiment_config(patch: dict[str, Any], why: str = "") -> ToolOutcome:
        return await _update_config({"patch": patch, "why": why}, context)

    @server.tool(name="validate_experiment", title="校验实验配置", description=_DESCRIPTION["validate_experiment"])
    @_guarded
    async def validate_experiment() -> ToolOutcome:
        return await _validate(context)

    @server.tool(name="run_simulation", title="运行仿真", description=_DESCRIPTION["run_simulation"])
    @_guarded
    async def run_simulation(reason: str) -> ToolOutcome:
        return await _run(context, authorization)

    @server.tool(
        name="compare_scheduling_policies",
        title="对比调度策略",
        description=_DESCRIPTION["compare_scheduling_policies"],
    )
    @_guarded
    async def compare_scheduling_policies(reason: str) -> ToolOutcome:
        return await _compare(context, authorization)

    @server.tool(name="calculate_metrics", title="读取最近指标", description=_DESCRIPTION["calculate_metrics"])
    @_guarded
    async def calculate_metrics() -> ToolOutcome:
        return _metrics(context)

    @server.tool(name="search_knowledge", title="查询平台资料", description=_DESCRIPTION["search_knowledge"])
    @_guarded
    async def search_knowledge(query: str, limit: int = 3) -> ToolOutcome:
        return _search_knowledge({"query": query, "limit": limit})

    return server
