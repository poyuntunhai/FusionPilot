"""
The client half of the in-process MCP transport.

It speaks the same two calls an out-of-process MCP client would — list the tools, call one — so the
loop is written against the protocol rather than against this project's tool table. The only
in-process concession is ``Client(server)``, which needs no subprocess or socket.

A tool error comes back as ``ToolOutcome(ok=False, error=...)`` rather than an exception: the loop
already has a path for "the tool said no" (it feeds the error back to the model), and an exception
here would turn a rejected configuration into a failed turn.
"""

from __future__ import annotations

from typing import Any

from mcp import Client
from mcp.server import MCPServer

from ..domain_tools import ToolOutcome


class ToolClient:
    def __init__(self, server: MCPServer) -> None:
        self._server = server

    async def list_tool_names(self) -> list[str]:
        """The names the server exposes. Used to prove the catalogue and the server agree."""
        async with Client(self._server) as client:
            result = await client.list_tools()
        return sorted(tool.name for tool in result.tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        async with Client(self._server) as client:
            result = await client.call_tool(name, arguments)

        if result.is_error:
            messages = [
                str(getattr(block, "text", ""))
                for block in result.content
                if getattr(block, "text", "")
            ]
            return ToolOutcome(ok=False, error="; ".join(messages) or f"tool failed: {name}")
        if result.structured_content is None:
            # Every tool returns a ToolOutcome, so a missing structured result means the tool was
            # registered with a return type the SDK could not structure — a wiring bug, not a
            # runtime condition, and it must not be mistaken for a successful empty answer.
            return ToolOutcome(ok=False, error=f"tool returned no structured result: {name}")
        return ToolOutcome.model_validate(result.structured_content)
