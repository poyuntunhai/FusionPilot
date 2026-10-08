"""
Tests for the LangGraph turn orchestration (intent routing + clarification).

The graph's job is to decide *where* a turn goes before anything runs:

* concept question  -> a tool-free answer, streamed token by token
* experiment        -> the existing tool-calling loop
* vague request     -> a clarification question, and the turn ends

These tests pin the routing itself. The loop's behaviour (confirmation gate, step budget, tool
execution) is already covered by ``test_multi_turn.py``; here the loop is a black box reached
through the ``experiment`` node.
"""

import asyncio
import json

import pytest

from app.agent_graph import (
    CLARIFY,
    CONCEPT_QA,
    EXPERIMENT,
    SupervisorDecision,
    classify_intent,
    run_turn,
)
from app.conversation import AgentMessage, ToolCallRecord
from app.model_gateway import ModelGatewayError, ModelStreamEvent, resolve_credential
from app.session_store import session_store


OWNER = 5150


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


def new_session():
    session_store.drop_for_user(OWNER)
    session = session_store.create(
        owner_user_id=OWNER,
        default_config=default_config(),
        provider="openai",
        model="gpt-4o-mini",
    )
    session.messages.append(AgentMessage(role="user", content="whatever"))
    return session


def events_of(session) -> list[str]:
    return [event.event_type for event in session.events]


def run(session, cred):
    return asyncio.run(run_turn(session, cred, "Bearer test"))


# --------------------------------------------------------------------------- routing


def test_a_concept_question_is_answered_without_tools(monkeypatch):
    async def fake_classify(session, cred):
        return SupervisorDecision(CONCEPT_QA, None, "test route")

    seen_tools = []

    async def fake_stream(system_prompt, messages, tools, cred):
        seen_tools.append(list(tools))
        yield ModelStreamEvent("text", text="卡尔曼滤波是")
        yield ModelStreamEvent("text", text="一种递归状态估计方法。")

    monkeypatch.setattr("app.agent_graph.classify_intent", fake_classify)
    monkeypatch.setattr("app.agent_graph.stream_call_with_tools", fake_stream)

    session = new_session()
    run(session, credential())

    assistant = [m for m in session.messages if m.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].tool_calls == []
    assert assistant[0].content == "卡尔曼滤波是一种递归状态估计方法。"
    assert assistant[0].produced_by == "openai:gpt-4o-mini"
    # The concept answer runs with an empty tool catalog, so the model cannot drift into a tool.
    assert seen_tools == [[]]
    assert "intent_classified" in events_of(session)
    assert "turn_completed" in events_of(session)


def test_an_experiment_request_reaches_the_tool_loop(monkeypatch):
    async def fake_classify(session, cred):
        return SupervisorDecision(EXPERIMENT, None, "test route")

    script = [
        [ModelStreamEvent("tool_calls", tool_calls=[ToolCallRecord(call_id="c1", name="get_experiment_config", arguments={})])],
        [ModelStreamEvent("text", text="here it is")],
    ]

    async def fake_stream(system_prompt, messages, tools_, cred):
        for event in (script.pop(0) if script else [ModelStreamEvent("text", text="done")]):
            yield event

    async def fake_validate(config):
        return {"valid": True}

    monkeypatch.setattr("app.agent_graph.classify_intent", fake_classify)
    monkeypatch.setattr("app.agent_loop.stream_call_with_tools", fake_stream)
    monkeypatch.setattr("app.domain_tools.validate_experiment", fake_validate)

    session = new_session()
    run(session, credential())

    assert [m.tool_name for m in session.messages if m.role == "tool"] == ["get_experiment_config"]
    assert "intent_classified" in events_of(session)


def test_a_vague_request_is_clarified_instead_of_guessed(monkeypatch):
    async def fake_classify(session, cred):
        return SupervisorDecision(CLARIFY, "你想先优化哪个指标：位置误差还是跟踪率？", "test route")

    monkeypatch.setattr("app.agent_graph.classify_intent", fake_classify)

    session = new_session()
    run(session, credential())

    assistant = [m for m in session.messages if m.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].content == "你想先优化哪个指标：位置误差还是跟踪率？"
    assert assistant[0].tool_calls == []
    assert session.status == "ACTIVE"
    # No tool was proposed, so the user answers the question and the next turn re-routes.
    assert "clarification_requested" in events_of(session)
    assert "turn_completed" in events_of(session)


# --------------------------------------------------------------------------- the classifier


def test_classify_without_a_credential_goes_to_the_loop():
    session = new_session()
    decision = asyncio.run(classify_intent(session, None))
    assert (decision.action, decision.question) == (EXPERIMENT, None)
    # A handoff with no stated reason is worse than a generic one, so rule mode still says why.
    assert decision.because


def test_classify_falls_back_to_experiment_when_the_model_fails(monkeypatch):
    async def failing_complete(messages, cred):
        raise ModelGatewayError("MODEL_UNAVAILABLE", "connection refused")

    monkeypatch.setattr("app.agent_graph.complete", failing_complete)
    session = new_session()
    decision = asyncio.run(classify_intent(session, credential()))
    assert (decision.action, decision.question) == (EXPERIMENT, None)
    assert decision.because


def test_classify_falls_back_when_the_model_returns_garbage(monkeypatch):
    async def garbage_complete(messages, cred):
        return "not json at all {{{{"

    monkeypatch.setattr("app.agent_graph.complete", garbage_complete)
    session = new_session()
    decision = asyncio.run(classify_intent(session, credential()))
    assert (decision.action, decision.question) == (EXPERIMENT, None)
    assert decision.because


def test_classify_requires_a_question_on_the_clarify_route(monkeypatch):
    async def clarify_without_question(messages, cred):
        return json.dumps({"action": "clarify", "question": ""})

    monkeypatch.setattr("app.agent_graph.complete", clarify_without_question)
    session = new_session()
    decision = asyncio.run(classify_intent(session, credential()))
    assert (decision.action, decision.question) == (EXPERIMENT, None)
    assert decision.because


def test_classify_hands_the_model_the_live_state(monkeypatch):
    captured = {}

    async def capture_complete(messages, cred):
        captured["messages"] = messages
        return json.dumps({"action": "concept_qa", "question": ""})

    monkeypatch.setattr("app.agent_graph.complete", capture_complete)
    session = new_session()
    session.working_config["targetCount"] = 7
    session.last_result = {"metrics": {"trackingRate": 0.5}, "runId": "run-9"}

    asyncio.run(classify_intent(session, credential()))

    user_payload = json.loads(captured["messages"][1]["content"])
    assert user_payload["working_config"]["targetCount"] == 7
    assert user_payload["last_run_metrics"]["trackingRate"] == 0.5
    assert captured["messages"][0]["role"] == "system"
