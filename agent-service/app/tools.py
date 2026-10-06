from typing import Any

from .java_client import (
    compare_scheduling_policies,
    run_simulation,
    validate_experiment,
)
from .models import ToolDefinition


TOOL_DEFINITIONS = [
    ToolDefinition(
        name="validate_experiment",
        description="Validate a structured experiment configuration in the Java backend.",
        input_schema={"type": "object", "required": ["config"]},
    ),
    ToolDefinition(
        name="run_simulation",
        description="Run one confirmed simulation through the Java simulation core.",
        input_schema={"type": "object", "required": ["config", "confirmation"]},
    ),
    ToolDefinition(
        name="calculate_metrics",
        description="Summarize metrics already returned by the Java simulation result.",
        input_schema={"type": "object", "required": ["simulation_result"]},
    ),
    ToolDefinition(
        name="compare_scheduling_policies",
        description="Run the Java comparison endpoint for configured scheduling policies.",
        input_schema={"type": "object", "required": ["config", "confirmation"]},
    ),
]


def list_tool_definitions() -> list[ToolDefinition]:
    return TOOL_DEFINITIONS


async def call_tool(tool_name: str, config: dict[str, Any], last_result: dict[str, Any] | None) -> dict[str, Any]:
    if tool_name == "validate_experiment":
        return await validate_experiment(config)
    if tool_name == "run_simulation":
        return await run_simulation(config)
    if tool_name == "compare_scheduling_policies":
        return await compare_scheduling_policies(config)
    if tool_name == "calculate_metrics":
        return calculate_metrics(last_result)
    raise ValueError(f"Unknown tool: {tool_name}")


def calculate_metrics(result: dict[str, Any] | None) -> dict[str, Any]:
    if not result:
        raise ValueError("A simulation result is required before calculating metrics.")
    metrics = result.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}
    return {
        "metrics": metrics,
        "source": "java-backend-result",
        "metricCount": len(metrics),
    }