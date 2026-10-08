from typing import Any, Literal

from pydantic import BaseModel, Field

from .conversation import AgentMessage, ToolCallRecord


SchedulingPolicy = Literal["ROUND_ROBIN", "PRIORITY"]
ToolName = Literal[
    "validate_experiment",
    "run_simulation",
    "calculate_metrics",
    "compare_scheduling_policies",
]

# NOTE ON SECRETS: no model here carries an API key. The key travels in the
# `X-Model-Api-Key` request header and is resolved into a ModelCredential per call, so it can
# never be serialised into a response, an event payload, or a persisted agent session.


class PlanRequest(BaseModel):
    goal: str = Field(min_length=5, max_length=1000)
    target_count: int | None = Field(default=None, ge=1, le=50)
    simulation_steps: int | None = Field(default=None, ge=1, le=10000)
    scheduling_policy: SchedulingPolicy | None = None
    compare_policies: bool = False
    model_provider: str | None = Field(default=None, max_length=40)
    model_name: str | None = Field(default=None, max_length=120)
    # Optional self-hosted or proxied endpoint for the selected provider.
    model_api_base_url: str | None = Field(default=None, max_length=400)


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
    planner: str = "rule"
    model: str | None = None
    # Which registered tool this plan should run next. The UI preselects it so the plan and the
    # execution step cannot drift apart.
    recommended_tool: ToolName | None = None
    # Set when a model was requested but the plan fell back to the local rule planner, so the
    # reason is visible instead of silent.
    planning_note: str | None = None


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
    # Which planner produced this reading: "rule", or "<provider>:<model>".
    produced_by: str = "rule"


class AgentTrace(BaseModel):
    trace_id: str
    owner_user_id: int
    request: PlanRequest
    plan: ExperimentPlan
    confirmed: bool = False
    status: str = "AWAITING_CONFIRMATION"
    events: list[TraceEvent] = Field(default_factory=list)
    last_result: dict[str, Any] | None = None
    analysis: ResultAnalysis | None = None


class ExecuteToolRequest(BaseModel):
    tool_name: ToolName
    model_provider: str | None = Field(default=None, max_length=40)
    model_name: str | None = Field(default=None, max_length=120)
    model_api_base_url: str | None = Field(default=None, max_length=400)


class ToolCallResult(BaseModel):
    trace_id: str
    tool_name: ToolName
    result: dict[str, Any]
    analysis: ResultAnalysis | None = None


class ConfirmResponse(BaseModel):
    trace_id: str
    confirmed: bool
    status: str


class ModelProbeRequest(BaseModel):
    """Body of the connection test. The API key itself travels in the request header."""

    provider: str = Field(max_length=40)
    model: str | None = Field(default=None, max_length=120)
    api_base_url: str | None = Field(default=None, max_length=400)


class ModelConnectionTest(BaseModel):
    provider: str
    label: str
    model: str
    reply: str


# --------------------------------------------------------------------------- multi-turn sessions


class PlanStep(BaseModel):
    """One step of an agent-proposed experiment sequence."""

    summary: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ExperimentSequence(BaseModel):
    """
    A multi-step experiment the agent designed for an exploratory goal.

    The steps are concrete tool calls, so the sequence is executable as-is once the user approves
    it: an ``update_experiment_config`` step changes the working configuration, a following
    ``run_simulation`` step runs under it. Approving the whole sequence at once is the point -
    otherwise a three-step comparison would need three separate confirmations.
    """

    goal: str
    rationale: str = ""
    steps: list[PlanStep] = Field(default_factory=list)
    # How the model that produced this is labelled, e.g. "openai:gpt-4o-mini".
    produced_by: str = "rule"


class PendingDecision(BaseModel):
    """
    Tool calls the model asked for that are waiting on the user.

    The whole batch is held, not just the first call: pausing halfway through a batch would leave
    the transcript with tool calls that never received a result, which both providers reject.
    """

    tool_calls: list[ToolCallRecord]
    prompt: str
    created_at: str


class AgentSession(BaseModel):
    """
    One conversation with the agent.

    ``working_config`` is the session's own copy of the experiment configuration, which is what
    lets a user say "raise the target count to six" and then "now run it" in two separate turns.
    """

    session_id: str
    owner_user_id: int
    title: str
    status: str = "ACTIVE"
    provider: str = "rule"
    model: str | None = None
    # When false, tools that change or spend resources wait for an explicit go-ahead.
    auto_approve: bool = False
    # Long-term note distilled from past conversations, loaded at session start and updated as the
    # agent learns. Carried on the session so it persists with the snapshot.
    memory: str = ""
    messages: list[AgentMessage] = Field(default_factory=list)
    events: list[TraceEvent] = Field(default_factory=list)
    working_config: dict[str, Any] = Field(default_factory=dict)
    default_config: dict[str, Any] = Field(default_factory=dict)
    plan: ExperimentPlan | None = None
    # A multi-step experiment the agent proposed for an exploratory goal, shown as a plan card and
    # awaiting one approval.
    sequence: ExperimentSequence | None = None
    # The structured reading of the most recent run, produced by the analyst role. Persisted with
    # the snapshot so a reloaded conversation still shows what the numbers were understood to mean,
    # and stored as an artifact rather than as prose so it can be checked against the metrics.
    analysis: ResultAnalysis | None = None
    pending: PendingDecision | None = None
    # Compact form: {"metrics": {...}, "runId": ...} rather than the full step-by-step payload.
    last_result: dict[str, Any] | None = None
    last_run_id: str | None = None
    last_evidence: list[dict[str, Any]] = Field(default_factory=list)
    last_limitations: list[str] = Field(default_factory=list)
    tool_call_count: int = 0
    created_at: str
    updated_at: str


class AgentSessionSummary(BaseModel):
    session_id: str
    title: str
    status: str
    provider: str
    model: str | None = None
    message_count: int = 0
    tool_call_count: int = 0
    working_summary: str = ""
    created_at: str
    updated_at: str


class SendMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    model_provider: str | None = Field(default=None, max_length=40)
    model_name: str | None = Field(default=None, max_length=120)
    model_api_base_url: str | None = Field(default=None, max_length=400)
    # Lets the UI flip the confirmation gate for this session without a second endpoint.
    auto_approve: bool | None = None


class ToolDecisionRequest(BaseModel):
    approve: bool = True
    model_provider: str | None = Field(default=None, max_length=40)
    model_name: str | None = Field(default=None, max_length=120)
    model_api_base_url: str | None = Field(default=None, max_length=400)


class NewSessionRequest(BaseModel):
    auto_approve: bool = False
    model_provider: str | None = Field(default=None, max_length=40)
    model_name: str | None = Field(default=None, max_length=120)
