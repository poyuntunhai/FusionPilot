from typing import Any, Literal

from pydantic import BaseModel, Field


SchedulingPolicy = Literal["ROUND_ROBIN", "PRIORITY"]
ToolName = Literal[
    "validate_experiment",
    "run_simulation",
    "calculate_metrics",
    "compare_scheduling_policies",
]


class PlanRequest(BaseModel):
    goal: str = Field(min_length=5, max_length=1000)
    target_count: int | None = Field(default=None, ge=1, le=50)
    simulation_steps: int | None = Field(default=None, ge=1, le=10000)
    scheduling_policy: SchedulingPolicy | None = None
    compare_policies: bool = False


class ExperimentPlan(BaseModel):
    title: str
    goal: str
    assumptions: list[str]
    experiment_config: dict[str, Any]
    baselines: list[str]
    metrics: list[str]
    execution_steps: list[str]
    expected_outputs: list[str]
    requires_confirmation: bool = True


class ToolRunRequest(BaseModel):
    config: dict[str, Any]
    confirmed: bool = False


class AgentError(BaseModel):
    code: str
    message: str
    dependency: str | None = None


class ToolDefinition(BaseModel):
    name: ToolName
    description: str
    input_schema: dict[str, Any]
    needs_confirmation: bool = True


class TraceEvent(BaseModel):
    event_id: str
    trace_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ResultAnalysis(BaseModel):
    summary: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AgentTrace(BaseModel):
    trace_id: str
    request: PlanRequest
    plan: ExperimentPlan
    confirmed: bool = False
    status: str = "AWAITING_CONFIRMATION"
    events: list[TraceEvent] = Field(default_factory=list)
    last_result: dict[str, Any] | None = None
    analysis: ResultAnalysis | None = None


class ExecuteToolRequest(BaseModel):
    tool_name: ToolName


class ToolCallResult(BaseModel):
    trace_id: str
    tool_name: ToolName
    result: dict[str, Any]
    analysis: ResultAnalysis | None = None


class ConfirmResponse(BaseModel):
    trace_id: str
    confirmed: bool
    status: str