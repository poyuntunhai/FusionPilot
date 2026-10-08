"""
Tests for autonomous experiment planning (the `explore` route).

An exploratory goal ("compare Kalman against weighted-average") is answered by a designed
multi-step sequence rather than a single action. The properties that matter:

* the plan becomes one pending batch, so the whole sequence is approved at once;
* approving it runs every step in order, with each run using the configuration its preceding
  ``update_experiment_config`` step set;
* a plan that cannot be built (no model, bad JSON, only unknown tools) degrades to the ordinary
  loop instead of stalling.
"""

import asyncio
import json

from app.agent_loop import resolve_decision
from app.agent_graph import run_turn
from app.conversation import AgentMessage, ToolCallRecord
from app.model_gateway import ModelGatewayError, ModelStreamEvent, resolve_credential
from app.session_store import session_store


OWNER = 7300


def default_config() -> dict:
    return {
        "scenarioName": "multi-target-demo",
        "targetCount": 3,
        "simulationSteps": 12,
        "timeStepSeconds": 1.0,
        "availableResources": 2,
        "fusionMethod": "WEIGHTED_AVERAGE",
        "schedulingPolicy": "ROUND_ROBIN",
        "randomSeed": 20260928,
        "observationSources": [],
    }


def credential():
    return resolve_credential("openai", "gpt-4o-mini", "user-token")


def new_session(**overrides):
    session_store.drop_for_user(OWNER)
    session = session_store.create(
        owner_user_id=OWNER,
        default_config=default_config(),
        auto_approve=False,
        provider="openai",
        model="gpt-4o-mini",
    )
    for key, value in overrides.items():
        setattr(session, key, value)
    session.messages.append(AgentMessage(role="user", content="对比加权平均和卡尔曼滤波的精度"))
    return session


def events_of(session) -> list[str]:
    return [event.event_type for event in session.events]


COMPARE_PLAN = {
    "goal": "对比置信度加权平均与卡尔曼滤波的定位精度",
    "rationale": "两个配置各跑一次，用同一场景直接比较平均位置误差。",
    "steps": [
        {"summary": "把融合方法设为加权平均", "tool": "update_experiment_config", "arguments": {"patch": {"fusionMethod": "WEIGHTED_AVERAGE"}}},
        {"summary": "跑加权平均", "tool": "run_simulation", "arguments": {"reason": "基线"}},
        {"summary": "把融合方法设为卡尔曼滤波", "tool": "update_experiment_config", "arguments": {"patch": {"fusionMethod": "KALMAN_FILTER"}}},
        {"summary": "跑卡尔曼滤波", "tool": "run_simulation", "arguments": {"reason": "对比"}},
    ],
}


def stub_planner(monkeypatch, plan: dict | None, classifier_action: str = "explore"):
    """Route to `explore` and answer the planner with `plan` (or fail the planner if None)."""

    async def fake_complete(messages, cred):
        system = messages[0]["content"]
        if "意图路由" in system:
            return json.dumps({"action": classifier_action, "question": ""})
        if "实验规划器" in system:
            if plan is None:
                raise ModelGatewayError("MODEL_UNAVAILABLE", "planner down")
            return json.dumps(plan, ensure_ascii=False)
        return "{}"

    seen = {"runs": [], "validations": []}

    async def fake_validate(config):
        seen["validations"].append(dict(config))
        return {"valid": True}

    async def fake_run(config, authorization=None):
        seen["runs"].append(dict(config))
        return {
            "runId": f"run-{len(seen['runs'])}",
            "config": dict(config),
            "metrics": {"averagePositionError": 1.0 + len(seen["runs"]), "trackingRate": 1.0},
            "steps": [{"timeStep": 0}],
        }

    monkeypatch.setattr("app.agent_graph.complete", fake_complete)
    monkeypatch.setattr("app.domain_tools.validate_experiment", fake_validate)
    monkeypatch.setattr("app.domain_tools.run_simulation", fake_run)

    # The fallback path still runs the ordinary loop, which calls the streaming model.
    async def fake_stream(system_prompt, messages, tools_, cred):
        yield ModelStreamEvent(
            "tool_calls",
            tool_calls=[ToolCallRecord(call_id="fb1", name="run_simulation", arguments={"reason": "fallback"})],
        )

    monkeypatch.setattr("app.agent_loop.stream_call_with_tools", fake_stream)
    return seen


# --------------------------------------------------------------------------- planning


def test_an_exploratory_goal_becomes_one_pending_plan(monkeypatch):
    stub_planner(monkeypatch, COMPARE_PLAN)
    session = new_session()

    asyncio.run(run_turn(session, credential(), "Bearer test"))

    assert session.sequence is not None
    assert len(session.sequence.steps) == 4
    assert session.status == "AWAITING_CONFIRMATION"
    # The whole sequence is one batch, so one approval covers every step.
    assert session.pending is not None
    assert [call.name for call in session.pending.tool_calls] == [
        "update_experiment_config",
        "run_simulation",
        "update_experiment_config",
        "run_simulation",
    ]
    assert "plan_created" in events_of(session)
    confirmation = [e for e in session.events if e.event_type == "confirmation_requested"][-1]
    assert confirmation.payload["is_plan"] is True


def test_approving_the_plan_runs_every_step_in_order(monkeypatch):
    seen = stub_planner(monkeypatch, COMPARE_PLAN)
    session = new_session()
    asyncio.run(run_turn(session, credential(), "Bearer test"))
    assert seen["runs"] == []

    asyncio.run(resolve_decision(session, True, credential(), "Bearer test"))

    # Both runs happened, and each used the configuration its preceding update set.
    assert [run["fusionMethod"] for run in seen["runs"]] == ["WEIGHTED_AVERAGE", "KALMAN_FILTER"]
    assert session.sequence is not None  # kept for the summary card
    assert session.last_run_id == "run-2"


def test_declining_the_plan_runs_nothing(monkeypatch):
    seen = stub_planner(monkeypatch, COMPARE_PLAN)
    session = new_session()
    asyncio.run(run_turn(session, credential(), "Bearer test"))

    asyncio.run(resolve_decision(session, False, credential(), "Bearer test"))

    assert seen["runs"] == []
    # Each declined step was closed out with a result, so the transcript still replays cleanly.
    declined = [m for m in session.messages if m.role == "tool" and m.tool_ok is False]
    assert len(declined) == 4


def test_unknown_tools_are_dropped_from_a_plan(monkeypatch):
    plan = {
        "goal": "x",
        "rationale": "y",
        "steps": [
            {"summary": "delete everything", "tool": "drop_all_tables", "arguments": {}},
            {"summary": "跑一次", "tool": "run_simulation", "arguments": {"reason": "r"}},
        ],
    }
    stub_planner(monkeypatch, plan)
    session = new_session()

    asyncio.run(run_turn(session, credential(), "Bearer test"))

    assert session.sequence is not None
    assert [step.tool for step in session.sequence.steps] == ["run_simulation"]


def test_a_plan_with_no_valid_step_falls_back_to_the_loop(monkeypatch):
    plan = {"goal": "x", "rationale": "y", "steps": [{"summary": "nope", "tool": "not_a_tool", "arguments": {}}]}
    seen = stub_planner(monkeypatch, plan)
    session = new_session()

    asyncio.run(run_turn(session, credential(), "Bearer test"))

    # No plan was stored, and the ordinary loop ran instead (it proposes a run, so it pauses).
    assert session.sequence is None
    assert "plan_created" not in events_of(session)


def test_a_failed_planner_call_falls_back_to_the_loop(monkeypatch):
    stub_planner(monkeypatch, None)
    session = new_session()

    asyncio.run(run_turn(session, credential(), "Bearer test"))

    assert session.sequence is None
    assert "plan_created" not in events_of(session)
