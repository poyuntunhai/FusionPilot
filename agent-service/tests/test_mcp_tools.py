"""
Tools now travel over MCP, and that has to be assertable.

Three things have to hold, or "going through MCP" is the same if/elif chain wearing a new name:

1. the tools the server exposes are exactly the ones in the catalogue the model is shown — two
   sources of truth would let a tool exist in one and not the other;
2. a call really round-trips through the transport and comes back with its result;
3. a crashing tool still comes back naming its exception class, because the loop uses that to tell
   "the tool said no" from "the tool crashed" and reports it to the model.
"""

from __future__ import annotations

import asyncio

import pytest

from app.domain_tools import TOOL_CATALOG, ToolContext
from app.mcp_runtime import ToolClient, build_tool_server


def _context() -> ToolContext:
    config = {"scenarioName": "mcp-test", "targetCount": 3}
    return ToolContext(working_config=dict(config), default_config=dict(config))


def _client(context: ToolContext | None = None) -> ToolClient:
    return ToolClient(build_tool_server(context or _context(), None))


def _call(name: str, arguments: dict | None = None):
    return asyncio.run(_client().call_tool(name, arguments or {}))


def test_the_server_exposes_exactly_the_catalogue_tools():
    """Model-facing catalogue and protocol-facing server must not drift apart."""
    exposed = asyncio.run(_client().list_tool_names())

    assert exposed == sorted(tool["name"] for tool in TOOL_CATALOG)


def test_a_call_round_trips_through_the_transport():
    outcome = _call("get_experiment_config")

    assert outcome.ok is True
    assert outcome.summary["working_config"]["targetCount"] == 3


def test_the_server_is_bound_to_the_context_it_was_built_with():
    """A tool reads the turn's context, so the server has to be bound to that exact object."""
    context = _context()
    context.working_config["targetCount"] = 7

    outcome = asyncio.run(_client(context).call_tool("get_experiment_config", {}))

    assert outcome.ok is True
    assert outcome.summary["working_config"]["targetCount"] == 7


def test_a_tool_with_nothing_to_read_says_no_through_the_transport():
    """The "no run yet" refusal is a failed outcome, not an exception — the loop needs it that way."""
    outcome = _call("calculate_metrics")

    assert outcome.ok is False
    assert outcome.error


def test_a_crashing_tool_is_reported_with_its_class_name(monkeypatch):
    async def exploding_run(config, authorization=None):
        raise RuntimeError("exploded")

    monkeypatch.setattr("app.domain_tools.run_simulation", exploding_run)

    outcome = _call("run_simulation", {"reason": "x"})

    assert outcome.ok is False
    assert "RuntimeError" in outcome.error


def test_an_unknown_tool_is_reported_rather_than_raised():
    outcome = _call("no_such_tool")

    assert outcome.ok is False
    assert outcome.error
