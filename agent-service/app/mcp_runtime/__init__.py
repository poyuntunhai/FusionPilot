"""
In-process MCP transport for this project's own tools.

Why MCP at all, for seven fixed tools and a single backend? Because the tool *definition* and the
tool *execution* are now separate things:

* ``domain_tools.TOOL_CATALOG`` declares what the tools are (names, parameter schemas, which need
  confirmation). Nothing about running them lives there any more.
* A server built here registers the implementations and exposes them over MCP; the agent reaches
  them through a client instead of an if/elif chain.

That split is what makes a tool pluggable: adding one is a catalogue entry plus a registration, and
a second server (a database, a file parser, an external MCP endpoint) can be composed in later
without touching the loop. The transport is in-process — ``Client(server)`` with no subprocess or
socket — because both ends run in the same FastAPI process, so the protocol costs microseconds and
buys a standard shape.
"""

from __future__ import annotations

from .client import ToolClient
from .server import build_tool_server

__all__ = ["ToolClient", "build_tool_server"]
