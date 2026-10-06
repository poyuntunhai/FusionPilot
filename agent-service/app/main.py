from fastapi import Depends, FastAPI, HTTPException

from .agent_service import (
    AgentWorkflowError,
    confirm_session,
    create_session,
    execute_session_tool,
)
from .auth import require_agent_user
from .java_client import JavaBackendError, get_default_config, run_simulation
from .model_gateway import ModelGatewayError, current_provider, provider_catalog
from .model_planner import build_plan_with_model
from .models import (
    AgentTrace,
    ConfirmResponse,
    ExecuteToolRequest,
    ExperimentPlan,
    PlanRequest,
    ToolCallResult,
    ToolRunRequest,
)
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
async def create_plan(
    request: PlanRequest,
    _auth: dict = Depends(require_agent_user),
) -> ExperimentPlan:
    try:
        default_config = await get_default_config()
    except JavaBackendError as exc:
        raise _java_error(exc) from exc
    try:
        return await build_plan_with_model(request, default_config)
    except ModelGatewayError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": exc.code, "message": exc.message, "dependency": "model-provider"},
        ) from exc


@app.get("/api/v1/agent/models")
async def models(_auth: dict = Depends(require_agent_user)) -> dict:
    return {"current": current_provider(), "providers": provider_catalog()}


@app.get("/api/v1/agent/tools")
async def tools(_auth: dict = Depends(require_agent_user)) -> dict:
    return {"tools": [tool.model_dump() for tool in list_tool_definitions()]}


@app.get("/api/v1/agent/tools/default-config")
async def default_config(_auth: dict = Depends(require_agent_user)) -> dict:
    try:
        return await get_default_config()
    except JavaBackendError as exc:
        raise _java_error(exc) from exc


@app.post("/api/v1/agent/tools/run-simulation")
async def execute_simulation(
    request: ToolRunRequest,
    auth: dict = Depends(require_agent_user),
) -> dict:
    if not request.confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONFIRMATION_REQUIRED",
                "message": "User confirmation is required before running a simulation.",
            },
        )
    try:
        return await run_simulation(request.config, auth["authorization"])
    except JavaBackendError as exc:
        raise _java_error(exc) from exc


@app.post("/api/v1/agent/sessions", response_model=AgentTrace)
async def create_agent_session(
    request: PlanRequest,
    auth: dict = Depends(require_agent_user),
) -> AgentTrace:
    try:
        return await create_session(request, auth["user_id"])
    except JavaBackendError as exc:
        raise _java_error(exc) from exc


@app.post("/api/v1/agent/sessions/{trace_id}/confirm", response_model=ConfirmResponse)
async def confirm_agent_session(
    trace_id: str,
    auth: dict = Depends(require_agent_user),
) -> ConfirmResponse:
    try:
        return confirm_session(trace_id, auth["user_id"])
    except AgentWorkflowError as exc:
        raise _workflow_error(exc) from exc


@app.post("/api/v1/agent/sessions/{trace_id}/execute", response_model=ToolCallResult)
async def execute_agent_tool(
    trace_id: str,
    request: ExecuteToolRequest,
    auth: dict = Depends(require_agent_user),
) -> ToolCallResult:
    try:
        return await execute_session_tool(
            trace_id,
            request,
            auth["authorization"],
            auth["user_id"],
        )
    except JavaBackendError as exc:
        raise _java_error(exc) from exc
    except AgentWorkflowError as exc:
        raise _workflow_error(exc) from exc


@app.get("/api/v1/agent/sessions/{trace_id}", response_model=AgentTrace)
async def get_agent_session(
    trace_id: str,
    auth: dict = Depends(require_agent_user),
) -> AgentTrace:
    from .trace import trace_store

    trace = trace_store.get(trace_id)
    if trace is None or trace.owner_user_id != auth["user_id"]:
        raise HTTPException(
            status_code=404,
            detail={"code": "TRACE_NOT_FOUND", "message": "Agent trace not found."},
        )
    return trace


def _java_error(exc: JavaBackendError) -> HTTPException:
    return HTTPException(
        status_code=401 if exc.status_code == 401 else 503,
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
