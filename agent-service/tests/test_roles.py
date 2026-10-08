"""
Tests for the specialist roles and what each one is allowed to do.

The claim this file exists to defend is that the roles differ in *power*, not just in wording:

* the executor is the only role with a tool channel, and its surface is enumerated;
* the concept responder and the analyst are tool-free **by construction**, because they call
  ``complete``, which has no tool parameter to pass. If ``complete`` ever grows one, both roles
  silently gain the ability to act on the simulation — so the absence is asserted, not assumed.

The rest covers the analyst's cost gate and its two failure modes, because a reading that is missing
when it should be there, or that fails the turn when the model misbehaves, are both defects a
green suite would not otherwise notice.
"""

import asyncio
import inspect
import json

from app import model_gateway
from app.agent_graph import (
    CLARIFY,
    CONCEPT_QA,
    EXPERIMENT,
    SPECIALISTS,
    analyze_turn,
    build_turn_graph,
    classify_intent,
    reflect_turn,
)
from app.agent_loop import advance, resolve_decision
from app.conversation import AgentMessage, ToolCallRecord
from app.domain_tools import EXECUTOR_TOOL_NAMES, PLANNABLE_TOOLS, tool_schemas_for_model
from app.model_gateway import ModelGatewayError, ModelStreamEvent, resolve_credential
from app.models import AgentSession
from app.session_store import session_store

OWNER = 7070

METRICS = {"averagePositionError": 3.12, "trackingRate": 0.98, "resourceUtilization": 0.9}


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


def new_session(with_metrics: bool = True) -> AgentSession:
    session_store.drop_for_user(OWNER)
    session = session_store.create(
        owner_user_id=OWNER,
        default_config=default_config(),
        provider="openai",
        model="gpt-4o-mini",
    )
    session.messages.append(AgentMessage(role="user", content="跑一次"))
    if with_metrics:
        session.last_result = {"metrics": dict(METRICS), "runId": "run-1"}
        session.last_run_id = "run-1"
    return session


# --------------------------------------------------------------------------- power, not wording


def test_the_roles_without_a_tool_channel_have_nowhere_to_put_one():
    """
    The structural half of the argument.

    A prompt that says "do not call tools" is a request. This is the reason the request cannot be
    broken: ``complete`` takes no tools, so the responder and the analyst are unable to act even if
    their prose says otherwise. The day someone adds a ``tools`` parameter to ``complete``, all of
    those roles gain tool access at once — so it is asserted here rather than left as an intention.
    """
    parameters = inspect.signature(model_gateway.complete).parameters
    assert "tools" not in parameters
    assert "tool_choice" not in parameters


def test_the_executor_surface_is_exactly_what_was_enumerated():
    """
    Widening the executor's powers should be a visible edit with a failing test.

    Without this, appending a tool to `TOOL_CATALOG` silently grants it, and the only place that
    would show up is a model deciding to use it.
    """
    assert {tool["name"] for tool in tool_schemas_for_model()} == set(EXECUTOR_TOOL_NAMES)
    # The read-only lookup is available to the executor (a question can come up mid-experiment) but
    # must never be a plan step: a lookup has nothing to contribute to an approved batch.
    assert "search_knowledge" in EXECUTOR_TOOL_NAMES
    assert "search_knowledge" not in PLANNABLE_TOOLS


def test_every_route_hands_off_to_a_named_specialist():
    assert set(SPECIALISTS) == {CONCEPT_QA, EXPERIMENT, "explore", CLARIFY}
    assert len(set(SPECIALISTS.values())) == len(SPECIALISTS)


def test_the_graph_nodes_are_the_specialists():
    graph = build_turn_graph()
    nodes = set(graph.get_graph().nodes)
    assert {"supervisor", "responder", "executor", "planner", "clarifier", "analyst", "critic"} <= nodes
    # The router was renamed to say what it is; the old name would be a second vocabulary for one
    # concept, which is how a graph stops being readable.
    assert "classify" not in nodes


# --------------------------------------------------------------------------- the supervisor


def test_the_handoff_always_carries_a_reason():
    decision = asyncio.run(classify_intent(new_session(), None))
    assert decision.action == EXPERIMENT
    assert decision.because
    assert decision.specialist == "executor"


def test_the_model_reason_is_used_and_a_missing_one_falls_back(monkeypatch):
    async def with_reason(messages, cred):
        return json.dumps({"action": "concept_qa", "because": "问的是原理"})

    monkeypatch.setattr("app.agent_graph.complete", with_reason)
    decision = asyncio.run(classify_intent(new_session(), credential()))
    assert (decision.action, decision.because, decision.specialist) == (
        CONCEPT_QA,
        "问的是原理",
        "responder",
    )

    async def without_reason(messages, cred):
        return json.dumps({"action": "concept_qa"})

    monkeypatch.setattr("app.agent_graph.complete", without_reason)
    decision = asyncio.run(classify_intent(new_session(), credential()))
    # A handoff with no stated reason is worse than a generic one.
    assert decision.because
    assert decision.action == CONCEPT_QA


# --------------------------------------------------------------------------- the analyst


def test_the_analyst_reads_a_run_into_a_persisted_artifact(monkeypatch):
    async def fake_analysis(messages, cred, json_mode=True):
        return json.dumps(
            {
                "summary": "位置误差 3.12。",
                "evidence": [{"metric": "averagePositionError", "value": 3.12, "note": "主指标"}],
                "limitations": ["单个种子"],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("app.result_analysis.complete", fake_analysis)
    session = new_session()

    asyncio.run(analyze_turn(session, credential(), produced_result=True))

    assert session.analysis is not None
    assert session.analysis.evidence[0]["metric"] == "averagePositionError"
    # The value is taken from the run, never from the model's restatement of it.
    assert session.analysis.evidence[0]["value"] == 3.12
    assert session.analysis.produced_by == "openai:gpt-4o-mini"
    assert "analysis_ready" in [event.event_type for event in session.events]


def test_the_analyst_is_not_paid_for_without_a_result():
    session = new_session()
    asyncio.run(analyze_turn(session, credential(), produced_result=False))
    assert session.analysis is None

    session = new_session(with_metrics=False)
    asyncio.run(analyze_turn(session, credential(), produced_result=True))
    assert session.analysis is None


def test_the_analyst_drops_a_metric_the_run_never_returned(monkeypatch):
    async def inventing_analysis(messages, cred, json_mode=True):
        return json.dumps(
            {
                "summary": "看起来不错。",
                "evidence": [
                    {"metric": "averagePositionError", "value": 3.12, "note": "ok"},
                    {"metric": "hallucinatedMetric", "value": 12345, "note": "编造"},
                ],
                "limitations": [],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("app.result_analysis.complete", inventing_analysis)
    session = new_session()

    asyncio.run(analyze_turn(session, credential(), produced_result=True))

    named = [row["metric"] for row in session.analysis.evidence]
    assert named == ["averagePositionError"]


def test_the_analyst_falls_back_to_the_deterministic_reading(monkeypatch):
    async def failing(messages, cred, json_mode=True):
        raise ModelGatewayError("MODEL_UNAVAILABLE", "connection refused")

    monkeypatch.setattr("app.result_analysis.complete", failing)
    session = new_session()

    asyncio.run(analyze_turn(session, credential(), produced_result=True))

    # The artifact still exists and says so, rather than the reading silently going missing.
    assert session.analysis is not None
    assert session.analysis.produced_by == "rule"
    assert any("解读模型调用失败" in item for item in session.analysis.limitations)


def test_a_provider_answering_with_prose_does_not_fail_the_turn(monkeypatch):
    """
    A decode failure is a failure to read, not a failure of the turn.

    The first version caught only ``ModelGatewayError``, so a provider that answered the analyst with
    a paragraph instead of JSON would have raised out of the turn and returned a 500 — the opposite
    of the best-effort contract this step was written under.
    """

    async def prose(messages, cred, json_mode=True):
        return "Sure! The position error looks fine to me."

    monkeypatch.setattr("app.result_analysis.complete", prose)
    session = new_session()

    asyncio.run(analyze_turn(session, credential(), produced_result=True))

    assert session.analysis is not None
    assert session.analysis.produced_by == "rule"


def test_the_critic_also_survives_an_unparseable_audit(monkeypatch):
    async def prose(messages, cred, json_mode=True):
        return "I reviewed it and it seems fine, no JSON here."

    monkeypatch.setattr("app.reflection.complete", prose)
    session = new_session()
    session.messages.append(AgentMessage(role="assistant", content="误差是 3.12。"))

    asyncio.run(reflect_turn(session, credential()))

    # The deterministic layer still reported, which is the point of splitting the two layers.
    assert "self_check" in [event.event_type for event in session.events]


# --------------------------------------------------------------------------- outside the graph


def test_the_approval_turn_reads_and_audits_the_result(monkeypatch):
    """
    The decision path is outside the graph, so both specialists have to be invoked explicitly.

    This is the same shape as the reflection gap found earlier, extended to the analyst: approving a
    run is the moment a reading becomes possible, and it is the one moment the graph is not involved.
    """
    script = [
        [ModelStreamEvent("tool_calls", tool_calls=[ToolCallRecord(call_id="c1", name="run_simulation", arguments={"reason": "x"})])],
        [ModelStreamEvent("text", text="运行完成。")],
    ]

    async def fake_stream(system_prompt, messages, tools_, cred):
        for event in (script.pop(0) if script else [ModelStreamEvent("text", text="done")]):
            yield event

    async def fake_run(config, authorization=None):
        return {"runId": "run-1", "config": dict(config), "metrics": dict(METRICS), "steps": [{"timeStep": 0}]}

    async def fake_complete(messages, cred, json_mode=True):
        system = messages[0]["content"]
        if "analysis module" in system:
            return json.dumps({"summary": "读完了。", "evidence": [], "limitations": []}, ensure_ascii=False)
        return json.dumps({"supported": True, "problem": "", "correction": ""})

    monkeypatch.setattr("app.agent_loop.stream_call_with_tools", fake_stream)
    monkeypatch.setattr("app.domain_tools.run_simulation", fake_run)
    monkeypatch.setattr("app.result_analysis.complete", fake_complete)
    monkeypatch.setattr("app.reflection.complete", fake_complete)

    session = new_session(with_metrics=False)
    asyncio.run(advance(session, credential(), "Bearer test"))
    assert session.pending is not None

    calls_before = session.tool_call_count
    asyncio.run(resolve_decision(session, True, credential(), "Bearer test"))
    produced = session.tool_call_count > calls_before
    asyncio.run(analyze_turn(session, credential(), produced))
    asyncio.run(reflect_turn(session, credential()))

    event_types = [event.event_type for event in session.events]
    assert produced is True
    assert session.analysis is not None
    assert "analysis_ready" in event_types
    assert "self_check" in event_types
