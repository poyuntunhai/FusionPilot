"""
Tests for the server-sent-event streaming endpoints.

The interesting property is the ordering of frames: new transcript messages must be delivered
before the event that describes them, and the stream must always close with the authoritative
session, whether the turn stopped normally, paused for approval, or failed.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.auth import require_agent_user
from app.main import app
from app.agent_graph import EXPERIMENT, SupervisorDecision
from app.model_gateway import ModelGatewayError, ModelStreamEvent, ModelTurn, resolve_credential
from app.session_store import session_store


OWNER = 777


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


def set_user(user_id=OWNER):
    app.dependency_overrides[require_agent_user] = lambda: {
        "authorization": "Bearer test-token",
        "user": {"userId": user_id},
        "user_id": user_id,
    }


def stub_storage(monkeypatch):
    stored: dict = {}

    async def fake_default_config():
        return default_config()

    async def fake_save(snapshot, authorization):
        stored[snapshot["session_id"]] = json.loads(json.dumps(snapshot))

    async def fake_find(session_id, authorization):
        return stored.get(session_id)

    async def fake_list(authorization, limit=30):
        return []

    async def fake_delete(session_id, authorization):
        stored.pop(session_id, None)

    async def fake_get_memory(authorization):
        return ""

    async def fake_save_memory(memory, authorization):
        return None

    async def fake_classify(session, credential):
        return SupervisorDecision(EXPERIMENT, None, "test route")

    monkeypatch.setattr("app.main.get_default_config", fake_default_config)
    monkeypatch.setattr("app.main.save_agent_conversation", fake_save)
    monkeypatch.setattr("app.main.find_agent_conversation", fake_find)
    monkeypatch.setattr("app.main.list_agent_conversations", fake_list)
    monkeypatch.setattr("app.main.delete_agent_conversation", fake_delete)
    monkeypatch.setattr("app.main.get_agent_memory", fake_get_memory)
    monkeypatch.setattr("app.main.save_agent_memory", fake_save_memory)
    monkeypatch.setattr("app.agent_graph.classify_intent", fake_classify)
    return stored


def stub_java(monkeypatch):
    async def fake_validate(config):
        return {"valid": True}

    async def fake_run(config, authorization=None):
        return {
            "runId": "run-1",
            "config": dict(config),
            "metrics": {"averagePositionError": 3.12, "trackingRate": 0.98},
            "steps": [{"timeStep": 0}],
        }

    monkeypatch.setattr("app.domain_tools.validate_experiment", fake_validate)
    monkeypatch.setattr("app.domain_tools.run_simulation", fake_run)


def script_model(monkeypatch, script):
    async def fake_stream(system_prompt, messages, tools, cred):
        turn = script.pop(0) if script else ModelTurn(text="Done.", tool_calls=[])
        if turn.text:
            yield ModelStreamEvent("text", text=turn.text)
        if turn.tool_calls:
            yield ModelStreamEvent("tool_calls", tool_calls=turn.tool_calls)

    monkeypatch.setattr("app.agent_loop.stream_call_with_tools", fake_stream)


def make_client(monkeypatch):
    stub_storage(monkeypatch)
    stub_java(monkeypatch)
    set_user()
    client = TestClient(app)
    return client


def parse_sse(text):
    frames = []
    for block in text.split("\n\n"):
        event = "message"
        data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                raw = line[len("data:"):].strip()
                data = json.loads(raw) if raw else None
        if data is not None:
            frames.append((event, data))
    return frames


def test_stream_runs_the_loop_and_closes_with_the_session(monkeypatch):
    from app.conversation import ToolCallRecord

    script_model(
        monkeypatch,
        [
            ModelTurn(
                text="",
                tool_calls=[ToolCallRecord(call_id="c1", name="get_experiment_config", arguments={})],
            ),
            ModelTurn(text="Here is the configuration.", tool_calls=[]),
        ],
    )
    client = make_client(monkeypatch)
    try:
        session_id = client.post("/api/v1/agent/conversations", json={}).json()["session_id"]
        response = client.post(
            f"/api/v1/agent/conversations/{session_id}/messages/stream",
            json={"message": "show me the config", "model_provider": "openai"},
            headers={"X-Model-Api-Key": "user-token"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = parse_sse(response.text)

        kinds = [kind for kind, _ in frames]
        assert kinds[0] == "message"
        assert frames[0][1]["role"] == "user"
        assert "session" == kinds[-1]

        progress_types = [data["event_type"] for kind, data in frames if kind == "progress"]
        assert "assistant_message" in progress_types
        assert "tool_called" in progress_types
        assert "tool_result" in progress_types
        assert "turn_completed" in progress_types

        final = frames[-1][1]
        assert final["session_id"] == session_id
        assert final["status"] == "ACTIVE"
        # Every assistant tool call got an answer before the stream closed.
        answered = {m["tool_call_id"] for m in final["messages"] if m["role"] == "tool"}
        for m in final["messages"]:
            if m["role"] == "assistant":
                for call in m["tool_calls"]:
                    assert call["call_id"] in answered

        # New messages are delivered exactly once, before the session frame.
        message_frames = [data for kind, data in frames if kind == "message"]
        assert len(message_frames) == len(final["messages"])
    finally:
        app.dependency_overrides.pop(require_agent_user, None)


def test_stream_pauses_for_approval_before_running(monkeypatch):
    from app.conversation import ToolCallRecord

    script_model(
        monkeypatch,
        [
            ModelTurn(
                text="",
                tool_calls=[
                    ToolCallRecord(call_id="c1", name="run_simulation", arguments={"reason": "baseline"})
                ],
            ),
        ],
    )
    client = make_client(monkeypatch)
    try:
        session_id = client.post("/api/v1/agent/conversations", json={}).json()["session_id"]
        response = client.post(
            f"/api/v1/agent/conversations/{session_id}/messages/stream",
            json={"message": "run it", "model_provider": "openai"},
            headers={"X-Model-Api-Key": "user-token"},
        )

        frames = parse_sse(response.text)
        progress_types = [data["event_type"] for kind, data in frames if kind == "progress"]
        # The request to run was emitted, but the run itself never happened.
        assert "confirmation_requested" in progress_types
        final = frames[-1][1]
        assert final["status"] == "AWAITING_CONFIRMATION"
        assert final["pending"]["tool_calls"][0]["name"] == "run_simulation"
        assert not any(m["tool_name"] == "run_simulation" for m in final["messages"] if m["role"] == "tool")
    finally:
        app.dependency_overrides.pop(require_agent_user, None)


def test_stream_reports_a_model_failure_instead_of_dying(monkeypatch):
    async def failing_call(system_prompt, messages, tools, cred):
        if False:
            yield
        raise ModelGatewayError("MODEL_UNAVAILABLE", "connection refused")

    monkeypatch.setattr("app.agent_loop.stream_call_with_tools", failing_call)
    client = make_client(monkeypatch)
    try:
        session_id = client.post("/api/v1/agent/conversations", json={}).json()["session_id"]
        response = client.post(
            f"/api/v1/agent/conversations/{session_id}/messages/stream",
            json={"message": "hello", "model_provider": "openai"},
            headers={"X-Model-Api-Key": "user-token"},
        )

        frames = parse_sse(response.text)
        kinds = [kind for kind, _ in frames]
        assert "error" in kinds
        error = frames[kinds.index("error")][1]
        assert error["code"] == "MODEL_UNAVAILABLE"
        # The transcript still holds the user's message, so the turn can simply be retried.
        final = frames[-1][1]
        assert [m["role"] for m in final["messages"]] == ["user"]
    finally:
        app.dependency_overrides.pop(require_agent_user, None)
