"""
The tools the multi-turn agent may call.

The surface is deliberately small and the arguments are deliberately thin. Earlier revisions had
the model emit a full experiment configuration, which it routinely got wrong: partial objects
that failed backend validation, or invented field names that were silently ignored. Here the
model can only *patch* the session's working configuration, and every patch is checked by the
Java core before it is kept. The model therefore never has to be trusted about configuration
validity -- it just has to say what it wants to change.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from .java_client import (
    JavaBackendError,
    compare_scheduling_policies,
    run_simulation,
    validate_experiment,
)


CONFIRMATION_REQUIRED = frozenset({"run_simulation", "compare_scheduling_policies"})

# Tools the experiment planner may put in a sequence. Planning is for *doing*, so the read-only
# reference lookup is excluded: a plan step that only reads documentation is not a step of an
# experiment. The tool itself stays available to the ordinary loop, which is where a lookup belongs.
PLANNABLE_TOOLS = frozenset(
    {"get_experiment_config", "update_experiment_config", "validate_experiment", "run_simulation"}
)

# The executor specialist's tool surface — everything the tool loop may offer a model. Spelled out
# as a constant so that widening the executor's powers is a visible change with a test on it, rather
# than a side effect of appending to TOOL_CATALOG. The other two roles that talk to a model have no
# tool channel at all: the concept responder and the analyst call `complete`, which cannot carry
# tools. That is what makes their limits structural instead of a request in a prompt.
EXECUTOR_TOOL_NAMES = frozenset(
    {
        "get_experiment_config",
        "update_experiment_config",
        "validate_experiment",
        "run_simulation",
        "compare_scheduling_policies",
        "calculate_metrics",
        "search_knowledge",
    }
)

# Shown next to every evidence card. The numbers come from Java; the model only narrates.
EVIDENCE_LIMITATIONS = [
    "These values were returned by the Java simulation core and are shown verbatim.",
    "Mean position error averages all targets over every step of a single random seed, so it is one sample rather than a Monte-Carlo estimate.",
    "Changing the random seed or the step count produces a different sample; compare runs only when those settings match.",
    "The simulation is deterministic: the same configuration and random seed reproduce bit-identical metrics, so equal numbers mean reproducibility, not a cached result. Each run still has its own run id and config summary.",
]


class ToolOutcome(BaseModel):
    """The result of one tool call, in both a model-facing and a UI-facing form."""

    ok: bool
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    run_id: str | None = None

    def as_model_content(self) -> str:
        payload: dict[str, Any] = {"ok": self.ok}
        if self.error:
            payload["error"] = self.error
        payload["result"] = self.summary
        return json.dumps(payload, ensure_ascii=False)


class ToolContext(BaseModel):
    """Mutable session state the tools read and write."""

    working_config: dict[str, Any]
    default_config: dict[str, Any] = Field(default_factory=dict)
    last_result: dict[str, Any] | None = None
    last_run_id: str | None = None


CONFIG_SUMMARY_KEYS = (
    "scenarioName",
    "targetCount",
    "simulationSteps",
    "timeStepSeconds",
    "availableResources",
    "fusionMethod",
    "schedulingPolicy",
    "randomSeed",
)


TOOL_CATALOG: list[dict[str, Any]] = [
    {
        "name": "get_experiment_config",
        "description": (
            "Read the experiment configuration this session is currently working with, plus the "
            "backend defaults. Call this before changing anything so you know the starting point."
        ),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "update_experiment_config",
        "description": (
            "Change one or more fields of the working configuration. Send only the fields you want "
            "to change. The Java core validates the whole configuration and rejects the change if "
            "it is invalid, so call this before running anything. Observation sources are a list of "
            "at most three objects with type, noiseStdDev, missingRate, delaySteps and confidence."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "object",
                    "description": "Fields to change, for example {\"targetCount\": 6}.",
                },
                "why": {"type": "string", "description": "One short sentence on the reason."},
            },
            "required": ["patch"],
            "additionalProperties": False,
        },
    },
    {
        "name": "validate_experiment",
        "description": (
            "Ask the Java core whether the working configuration is acceptable, without running it. "
            "Use this when you want to confirm a setting before spending a simulation run."
        ),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "run_simulation",
        "description": (
            "Run one simulation with the working configuration and return its metrics. This is the "
            "tool that produces results. It requires the user's confirmation, so explain what you "
            "are about to run. The metrics you receive are the only results you may quote."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "What this run is meant to establish, shown to the user before they confirm.",
                }
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
        "needs_confirmation": True,
    },
    {
        "name": "compare_scheduling_policies",
        "description": (
            "Run the same configuration under round-robin and priority scheduling and return both "
            "results plus their differences. Requires the user's confirmation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "What the comparison is meant to establish, shown to the user before they confirm.",
                }
            },
            "required": ["reason"],
            "additionalProperties": False,
        },
        "needs_confirmation": True,
    },
    {
        "name": "calculate_metrics",
        "description": (
            "Re-read the metrics of the most recent run in this session without running anything "
            "again. Fails if nothing has been run yet."
        ),
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "search_knowledge",
        "description": (
            "Look up this platform's own reference material: what each configuration field means and "
            "its valid range, what each fusion method and scheduling policy actually does, how each "
            "metric is defined, what the observation model assumes, and what the platform does not "
            "model. Call this before answering anything about the platform's behaviour or its "
            "limitations rather than relying on general knowledge, and call it when you need a valid "
            "enum value or field name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to look up, e.g. \"KALMAN_FILTER\" or \"资源利用率 定义\".",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of sections to return (1-5, default 3).",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


def tool_schemas_for_model() -> list[dict[str, Any]]:
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"],
        }
        for tool in TOOL_CATALOG
    ]


def needs_confirmation(tool_name: str) -> bool:
    return tool_name in CONFIRMATION_REQUIRED


def describe_pending(tool_name: str, arguments: dict[str, Any]) -> str:
    reason = str(arguments.get("reason") or "").strip()
    if tool_name == "run_simulation":
        base = "Run a simulation with the current configuration."
    elif tool_name == "compare_scheduling_policies":
        base = "Run round-robin and priority scheduling on the current configuration and compare them."
    else:
        base = f"Call {tool_name}."
    return f"{base} Reason given: {reason}" if reason else base


async def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    context: ToolContext,
    authorization: str | None,
) -> ToolOutcome:
    if tool_name == "get_experiment_config":
        return ToolOutcome(
            ok=True,
            summary={
                "working_config": context.working_config,
                "default_config": context.default_config,
            },
        )
    if tool_name == "update_experiment_config":
        return await _update_config(arguments, context)
    if tool_name == "validate_experiment":
        return await _validate(context)
    if tool_name == "run_simulation":
        return await _run(context, authorization)
    if tool_name == "compare_scheduling_policies":
        return await _compare(context, authorization)
    if tool_name == "calculate_metrics":
        return _metrics(context)
    if tool_name == "search_knowledge":
        return _search_knowledge(arguments)
    return ToolOutcome(ok=False, error=f"Unknown tool: {tool_name}")


def _search_knowledge(arguments: dict[str, Any]) -> ToolOutcome:
    """
    Read the platform's own reference material.

    Deliberately a tool as well as a graph step: the concept route retrieves before it answers, but a
    question that comes up *during* an experiment turn ("does this filter estimate velocity?") needs
    the same material, and this is how the loop reaches it.
    """
    from .knowledge import citations, render_context, retrieve

    query = str(arguments.get("query") or "").strip()
    if not query:
        return ToolOutcome(ok=False, error="`query` must be a non-empty string.")

    raw_limit = arguments.get("limit")
    try:
        limit = max(1, min(5, int(raw_limit))) if raw_limit is not None else 3
    except (TypeError, ValueError):
        limit = 3

    hits = retrieve(query, limit=limit)
    if not hits:
        # Reported as a successful lookup with no match, so the model can say it has no material
        # instead of reading the absence as a broken tool and retrying.
        return ToolOutcome(
            ok=True,
            summary={
                "query": query,
                "matches": [],
                "note": (
                    "No section of the platform reference material matches this query. Say that you "
                    "have no material on it rather than answering from general knowledge."
                ),
            },
        )
    return ToolOutcome(
        ok=True,
        summary={
            "query": query,
            "matches": citations(hits),
            "excerpt": render_context(hits),
        },
    )


async def _update_config(arguments: dict[str, Any], context: ToolContext) -> ToolOutcome:
    patch = arguments.get("patch")
    if not isinstance(patch, dict) or not patch:
        return ToolOutcome(
            ok=False,
            error="`patch` must be a non-empty object of fields to change.",
        )

    allowed = set(context.working_config) | set(context.default_config)
    unknown = sorted(key for key in patch if key not in allowed)
    if unknown:
        return ToolOutcome(
            ok=False,
            error=(
                f"Unknown configuration field(s): {', '.join(unknown)}. "
                f"Valid fields are: {', '.join(sorted(allowed))}."
            ),
        )

    candidate = dict(context.working_config)
    candidate.update(patch)
    try:
        await validate_experiment(candidate)
    except JavaBackendError as exc:
        # Nothing is applied when Java refuses the configuration, so a rejected patch cannot
        # leave the session holding a configuration that cannot be run.
        return ToolOutcome(
            ok=False,
            error=f"The Java core rejected this configuration: {exc.message} The change was not applied.",
        )

    context.working_config = candidate
    return ToolOutcome(
        ok=True,
        summary={
            "applied": patch,
            "working_config": {key: candidate.get(key) for key in CONFIG_SUMMARY_KEYS if key in candidate},
        },
    )


async def _validate(context: ToolContext) -> ToolOutcome:
    try:
        result = await validate_experiment(context.working_config)
    except JavaBackendError as exc:
        return ToolOutcome(ok=False, error=f"The Java core rejected this configuration: {exc.message}")
    return ToolOutcome(ok=True, summary={"valid": True, "response": result})


async def _run(context: ToolContext, authorization: str | None) -> ToolOutcome:
    try:
        result = await run_simulation(context.working_config, authorization)
    except JavaBackendError as exc:
        return ToolOutcome(ok=False, error=f"The simulation could not run: {exc.message}")

    outcome = _outcome_from_result(result, "Simulation completed.")
    _remember(context, outcome)
    return outcome


async def _compare(context: ToolContext, authorization: str | None) -> ToolOutcome:
    try:
        result = await compare_scheduling_policies(context.working_config, authorization)
    except JavaBackendError as exc:
        return ToolOutcome(ok=False, error=f"The comparison could not run: {exc.message}")

    outcome = _outcome_from_result(result, "Comparison completed.")
    _remember(context, outcome)
    return outcome


def _remember(context: ToolContext, outcome: ToolOutcome) -> None:
    """
    Keep only the metrics of the most recent run.

    The full result carries every step of every target and is already persisted by the Java core
    against its own run id, so holding it in the session would duplicate megabytes for data the
    agent never reads back. The run id is what the frontend follows.
    """
    context.last_result = {
        "metrics": outcome.summary.get("metrics", {}),
        "runId": outcome.run_id,
    }
    context.last_run_id = outcome.run_id


def _metrics(context: ToolContext) -> ToolOutcome:
    if not context.last_result:
        return ToolOutcome(
            ok=False,
            error="No run has happened in this session yet, so there are no metrics to read.",
        )
    outcome = _outcome_from_result(context.last_result, "Metrics re-read from the last run.")
    return outcome


def _outcome_from_result(result: dict[str, Any], message: str) -> ToolOutcome:
    """
    Turn a raw Java payload into a compact tool outcome.

    The full step-by-step arrays stay in the Java store; only the scalars travel onward. Sending a
    sixty-step result back into the model's context would spend the window on data the model
    cannot use, so the model sees metrics while the frontend links to the stored run instead.
    """
    from .result_analysis import analyze_result, extract_metrics

    metrics = extract_metrics(result if isinstance(result, dict) else {})
    analysis = analyze_result(result if isinstance(result, dict) else {})

    config = result.get("config") if isinstance(result, dict) else None
    config_summary = (
        {key: config.get(key) for key in CONFIG_SUMMARY_KEYS if key in config}
        if isinstance(config, dict)
        else {}
    )
    steps = result.get("steps") if isinstance(result, dict) else None
    summary: dict[str, Any] = {
        "message": message,
        "metrics": metrics,
        "config": config_summary,
        "stepCount": len(steps) if isinstance(steps, list) else None,
    }
    run_id = result.get("runId") if isinstance(result, dict) else None
    if run_id:
        summary["runId"] = run_id

    return ToolOutcome(
        ok=True,
        summary=summary,
        evidence=analysis.evidence,
        limitations=list(EVIDENCE_LIMITATIONS),
        run_id=str(run_id) if run_id else None,
    )
