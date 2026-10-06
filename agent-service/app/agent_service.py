from typing import Any

from .java_client import JavaBackendError, get_default_config
from .models import (
    AgentTrace,
    ConfirmResponse,
    ExecuteToolRequest,
    PlanRequest,
    ResultAnalysis,
    ToolCallResult,
)
from .rules import build_plan
from .tools import call_tool
from .trace import trace_store


class AgentWorkflowError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def create_session(request: PlanRequest) -> AgentTrace:
    try:
        default_config = await get_default_config()
    except JavaBackendError:
        raise
    plan = build_plan(request, default_config)
    trace = trace_store.create(request, plan)
    trace_store.append(trace.trace_id, "request_received", {"goal": request.goal})
    trace_store.append(
        trace.trace_id,
        "plan_created",
        {"experiment_config": plan.experiment_config, "metrics": plan.metrics},
    )
    trace_store.append(
        trace.trace_id,
        "confirmation_requested",
        {"reason": "Simulation and comparison tools require user confirmation."},
    )
    return trace


def confirm_session(trace_id: str) -> ConfirmResponse:
    trace = _require_trace(trace_id)
    trace_store.update(trace_id, confirmed=True, status="CONFIRMED")
    trace_store.append(trace_id, "confirmation_received", {"confirmed": True})
    return ConfirmResponse(
        trace_id=trace_id,
        confirmed=True,
        status="CONFIRMED",
    )


async def execute_session_tool(trace_id: str, request: ExecuteToolRequest) -> ToolCallResult:
    trace = _require_trace(trace_id)
    if not trace.confirmed:
        raise AgentWorkflowError(
            "CONFIRMATION_REQUIRED",
            "User confirmation is required before executing an Agent tool.",
            409,
        )
    trace_store.append(
        trace_id,
        "tool_called",
        {"tool_name": request.tool_name, "config": trace.plan.experiment_config},
    )
    try:
        result = await call_tool(
            request.tool_name,
            trace.plan.experiment_config,
            trace.last_result,
        )
    except ValueError as exc:
        raise AgentWorkflowError("INVALID_TOOL_INPUT", str(exc), 400) from exc
    trace_store.update(
        trace_id,
        status="COMPLETED",
        last_result=result,
        analysis=analyze_result(result),
    )
    trace_store.append(
        trace_id,
        "tool_result",
        {"tool_name": request.tool_name, "result_keys": list(result.keys())},
    )
    trace_store.append(
        trace_id,
        "analysis_created",
        {"metric_keys": list((trace.analysis.metrics if trace.analysis else {}).keys())},
    )
    return ToolCallResult(
        trace_id=trace_id,
        tool_name=request.tool_name,
        result=result,
        analysis=trace.analysis,
    )


def analyze_result(result: dict[str, Any]) -> ResultAnalysis:
    metrics = result.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}
    evidence = [
        {"metric": key, "value": value, "source": "java-backend-result"}
        for key, value in metrics.items()
    ]
    return ResultAnalysis(
        summary="Analysis is limited to structured metrics returned by the Java backend.",
        metrics=metrics,
        evidence=evidence,
        limitations=[
            "The current Agent uses deterministic rules instead of a remote language model.",
            "No conclusion is inferred when a metric is absent from the structured result.",
        ],
    )


def _require_trace(trace_id: str) -> AgentTrace:
    trace = trace_store.get(trace_id)
    if trace is None:
        raise AgentWorkflowError(
            "TRACE_NOT_FOUND",
            f"Agent trace not found: {trace_id}",
            404,
        )
    return trace