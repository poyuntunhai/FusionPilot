from typing import Any

from .java_client import JavaBackendError, get_default_config
from .model_gateway import ModelCredential, ModelGatewayError
from .model_planner import build_plan_with_model
from .models import (
    AgentTrace,
    ConfirmResponse,
    ExecuteToolRequest,
    PlanRequest,
    ResultAnalysis,
    ToolCallResult,
)
from .result_analysis import analyze_result, analyze_with_model
from .tools import call_tool
from .trace import trace_store


__all__ = [
    "AgentWorkflowError",
    "analyze_result",
    "confirm_session",
    "create_session",
    "execute_session_tool",
]


class AgentWorkflowError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def create_session(
    request: PlanRequest,
    owner_user_id: int,
    credential: ModelCredential | None = None,
) -> AgentTrace:
    try:
        default_config = await get_default_config()
    except JavaBackendError:
        raise
    plan = await build_plan_with_model(request, default_config, credential)
    trace = trace_store.create(request, plan, owner_user_id)
    trace_store.append(trace.trace_id, "request_received", {"goal": request.goal})
    trace_store.append(
        trace.trace_id,
        "plan_created",
        {
            "experiment_config": plan.experiment_config,
            "metrics": plan.metrics,
            "planner": plan.planner,
            "model": plan.model,
            "recommended_tool": plan.recommended_tool,
        },
    )
    trace_store.append(
        trace.trace_id,
        "confirmation_requested",
        {"reason": "Simulation and comparison tools require user confirmation."},
    )
    return trace


def confirm_session(trace_id: str, owner_user_id: int) -> ConfirmResponse:
    _require_trace(trace_id, owner_user_id)
    trace_store.update(trace_id, confirmed=True, status="CONFIRMED")
    trace_store.append(trace_id, "confirmation_received", {"confirmed": True})
    return ConfirmResponse(
        trace_id=trace_id,
        confirmed=True,
        status="CONFIRMED",
    )


async def execute_session_tool(
    trace_id: str,
    request: ExecuteToolRequest,
    authorization: str | None = None,
    owner_user_id: int | None = None,
    credential: ModelCredential | None = None,
) -> ToolCallResult:
    trace = _require_trace(trace_id, owner_user_id)
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
            authorization,
        )
    except ValueError as exc:
        raise AgentWorkflowError("INVALID_TOOL_INPUT", str(exc), 400) from exc

    analysis = await _build_analysis(result, trace, credential)
    trace_store.update(
        trace_id,
        status="COMPLETED",
        last_result=result,
        analysis=analysis,
    )
    trace_store.append(
        trace_id,
        "tool_result",
        {"tool_name": request.tool_name, "result_keys": list(result.keys())},
    )
    trace_store.append(
        trace_id,
        "analysis_created",
        {
            "produced_by": analysis.produced_by,
            "metric_keys": list(analysis.metrics.keys()),
        },
    )
    return ToolCallResult(
        trace_id=trace_id,
        tool_name=request.tool_name,
        result=result,
        analysis=analysis,
    )


async def _build_analysis(
    result: dict[str, Any],
    trace: AgentTrace,
    credential: ModelCredential | None,
) -> ResultAnalysis:
    """
    Interpret the tool result.

    A model failure must never discard the simulation result that the tool already produced, so
    any gateway error degrades to the deterministic metric summary with the reason attached.
    """
    if credential is None:
        return analyze_result(result)
    try:
        return await analyze_with_model(result, trace.plan, credential)
    except ModelGatewayError as exc:
        fallback = analyze_result(result)
        return fallback.model_copy(
            update={
                "produced_by": f"{credential.provider}:{credential.model} (unavailable)",
                "limitations": fallback.limitations
                + [f"The model could not be reached, so this reading is metric-only: {exc.message}"],
            }
        )


def _require_trace(trace_id: str, owner_user_id: int | None = None) -> AgentTrace:
    trace = trace_store.get(trace_id)
    if trace is None or (owner_user_id is not None and trace.owner_user_id != owner_user_id):
        raise AgentWorkflowError(
            "TRACE_NOT_FOUND",
            f"Agent trace not found: {trace_id}",
            404,
        )
    return trace
