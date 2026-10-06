from fastapi import FastAPI, HTTPException

from .agent_service import (
    AgentWorkflowError,
    confirm_session,
    create_session,
    execute_session_tool,
)
from .java_client import JavaBackendError, get_default_config, run_simulation
from .models import (
    AgentTrace,
    ConfirmResponse,
    ExecuteToolRequest,
    ExperimentPlan,
    PlanRequest,
    ToolCallResult,
    ToolRunRequest,
)
from .rules import build_plan
from .tools import list_tool_definitions

app = FastAPI(
    title="FusionPilot Agent Service",
    version="0.2.0",
)


@app.get("/api/v1/agent/health")
async def health() -> dict:
    return {
        "service": "fusionpilot-agent",
        "status": "UP",
        "mode": "rule-based",
        "workflow": "tool-loop-with-trace",
    }


@app.post("/api/v1/agent/plan", response_model=ExperimentPlan)
async def create_plan(request: PlanRequest) -> ExperimentPlan:
    try:
        default_config = await get_default_config()
    except JavaBackendError as exc:
        raise _java_error(exc) from exc
    return build_plan(request, default_config)


@app.get("/api/v1/agent/tools")
async def tools() -> dict:
    return {"tools": [tool.model_dump() for tool in list_tool_definitions()]}


@app.get("/api/v1/agent/tools/default-config")
async def default_config() -> dict:
    try:
        return await get_default_config()
    except JavaBackendError as exc:
        raise _java_error(exc) from exc


@app.post("/api/v1/agent/tools/run-simulation")
async def execute_simulation(request: ToolRunRequest) -> dict:
    if not request.confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONFIRMATION_REQUIRED",
                "message": "User confirmation is required before running a simulation.",
            },
        )
    try:
        return await run_simulation(request.config)
    except JavaBackendError as exc:
        raise _java_error(exc) from exc


@app.post("/api/v1/agent/sessions", response_model=AgentTrace)
async def create_agent_session(request: PlanRequest) -> AgentTrace:
    try:
        return await create_session(request)
    except JavaBackendError as exc:
        raise _java_error(exc) from exc


@app.post("/api/v1/agent/sessions/{trace_id}/confirm", response_model=ConfirmResponse)
async def confirm_agent_session(trace_id: str) -> ConfirmResponse:
    try:
        return confirm_session(trace_id)
    except AgentWorkflowError as exc:
        raise _workflow_error(exc) from exc


@app.post("/api/v1/agent/sessions/{trace_id}/execute", response_model=ToolCallResult)
async def execute_agent_tool(trace_id: str, request: ExecuteToolRequest) -> ToolCallResult:
    try:
        return await execute_session_tool(trace_id, request)
    except JavaBackendError as exc:
        raise _java_error(exc) from exc
    except AgentWorkflowError as exc:
        raise _workflow_error(exc) from exc


@app.get("/api/v1/agent/sessions/{trace_id}", response_model=AgentTrace)
async def get_agent_session(trace_id: str) -> AgentTrace:
    from .trace import trace_store

    trace = trace_store.get(trace_id)
    if trace is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "TRACE_NOT_FOUND", "message": "Agent trace not found."},
        )
    return trace


def _java_error(exc: JavaBackendError) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": exc.code,
            "message": exc.message,
            "dependency": "java-backend",
        },
    )


def _workflow_error(exc: AgentWorkflowError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )