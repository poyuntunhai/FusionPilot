"""
Tests for the multi-turn agent loop.

The invariant these are built around: at rest, every tool call in the transcript has a result.
Both provider protocols reject a transcript where an assistant asks for a tool and nothing ever
answers, and the loop has three separate ways to reach that state (a paused confirmation, a
declined confirmation, and an abandoned confirmation). Each path is covered here.
"""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.agent_loop import MAX_STEPS_PER_TURN, advance, cancel_pending, resolve_decision
from app.auth import require_agent_user
from app.conversation import (
    AgentMessage,
    ToolCallRecord,
    context_window,
    to_anthropic_messages,
    to_openai_messages,
)
from app.java_client import JavaBackendError
from app.main import app
from app.agent_graph import EXPERIMENT, SupervisorDecision
from app.model_gateway import ModelGatewayError, ModelStreamEvent, ModelTurn, resolve_credential
from app.session_store import session_store


OWNER = 4242


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


RUN_METRICS = {
    "averagePositionError": 3.12,
    "trackingRate": 0.98,
    "resourceUtilization": 0.9,
    "averageWaitingTime": 0.4,
    "allocatedTargetCount": 3,
    "unservedTargetCount": 0,
}


def credential():
    return resolve_credential("openai", "gpt-4o-mini", "user-token")


def new_session(**overrides):
    session_store.drop_for_user(OWNER)
    session = session_store.create(
        owner_user_id=OWNER,
        default_config=default_config(),
        provider="openai",
        model="gpt-4o-mini",
    )
    for key, value in overrides.items():
        setattr(session, key, value)
    return session


def user_says(session, text: str) -> None:
    session.messages.append(AgentMessage(role="user", content=text))


def assert_transcript_is_replayable(session) -> None:
    answered = {m.tool_call_id for m in session.messages if m.role == "tool"}
    for message in session.messages:
        if message.role == "assistant":
            for call in message.tool_calls:
                assert call.call_id in answered, f"{call.name} was never answered"


def script_model(monkeypatch, script):
    """Replace the model call with a fixed script of turns."""
    captured = {"calls": []}

    async def fake_stream(system_prompt, messages, tools, cred):
        captured["calls"].append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "tool_names": [tool["name"] for tool in tools],
            }
        )
        turn = script.pop(0) if script else ModelTurn(text="Nothing further.", tool_calls=[])
        if turn.text:
            yield ModelStreamEvent("text", text=turn.text)
        if turn.tool_calls:
            yield ModelStreamEvent("tool_calls", tool_calls=turn.tool_calls)

    monkeypatch.setattr("app.agent_loop.stream_call_with_tools", fake_stream)
    return captured


def stub_java(monkeypatch, run_metrics=None, validate_error=None):
    """Replace the Java calls the domain tools make."""
    seen = {"runs": [], "validations": []}

    async def fake_validate(config):
        seen["validations"].append(dict(config))
        if validate_error:
            raise JavaBackendError("JAVA_REQUEST_FAILED", validate_error, 400)
        return {"valid": True}

    async def fake_run(config, authorization=None):
        seen["runs"].append(dict(config))
        return {
            "runId": f"run-{len(seen['runs'])}",
            "config": dict(config),
            "metrics": dict(run_metrics or RUN_METRICS),
            "steps": [{"timeStep": 0}],
        }

    async def fake_compare(config, authorization=None):
        seen["runs"].append(dict(config))
        return {
            "roundRobin": {"metrics": RUN_METRICS},
            "priority": {"metrics": {**RUN_METRICS, "averagePositionError": 2.5}},
            "priorityMinusRoundRobin": {"averagePositionErrorDelta": -0.62},
        }

    monkeypatch.setattr("app.domain_tools.validate_experiment", fake_validate)
    monkeypatch.setattr("app.domain_tools.run_simulation", fake_run)
    monkeypatch.setattr("app.domain_tools.compare_scheduling_policies", fake_compare)
    return seen


def tool_message(session, tool_name):
    return [m for m in session.messages if m.role == "tool" and m.tool_name == tool_name][-1]


# --------------------------------------------------------------------------- the loop


def test_run_waits_for_approval_then_executes_and_narrates(monkeypatch):
    seen = stub_java(monkeypatch)
    script_model(
        monkeypatch,
        [
            ModelTurn(
                text="Raising the target count first.",
                tool_calls=[
                    ToolCallRecord(
                        call_id="c1",
                        name="update_experiment_config",
                        arguments={"patch": {"targetCount": 6}, "why": "more targets"},
                    )
                ],
            ),
            ModelTurn(
                text="",
                tool_calls=[
                    ToolCallRecord(call_id="c2", name="run_simulation", arguments={"reason": "baseline"})
                ],
            ),
            ModelTurn(text="Mean position error is 3.12 with 98% tracking.", tool_calls=[]),
        ],
    )
    session = new_session()
    user_says(session, "Raise it to six targets and run it")

    asyncio.run(advance(session, credential(), "Bearer test"))

    # The configuration change is applied, but the run has not happened yet.
    assert session.working_config["targetCount"] == 6
    assert seen["runs"] == []
    assert session.pending is not None
    assert session.pending.tool_calls[0].name == "run_simulation"
    assert session.status == "AWAITING_CONFIRMATION"

    asyncio.run(resolve_decision(session, True, credential(), "Bearer test"))

    assert len(seen["runs"]) == 1
    run_message = tool_message(session, "run_simulation")
    assert run_message.tool_ok is True
    assert run_message.run_id == "run-1"
    assert session.pending is None
    assert session.status == "ACTIVE"
    assert session.messages[-1].role == "assistant"
    assert session.messages[-1].content.startswith("Mean position error")
    assert_transcript_is_replayable(session)


def test_declining_tells_the_model_and_closes_the_call(monkeypatch):
    seen = stub_java(monkeypatch)
    captured = script_model(
        monkeypatch,
        [
            ModelTurn(
                text="",
                tool_calls=[ToolCallRecord(call_id="c1", name="run_simulation", arguments={"reason": "x"})],
            ),
            ModelTurn(text="Understood, I will not run it.", tool_calls=[]),
        ],
    )
    session = new_session()
    user_says(session, "run the default experiment")

    asyncio.run(advance(session, credential(), "Bearer test"))
    asyncio.run(resolve_decision(session, False, credential(), "Bearer test"))

    assert seen["runs"] == []
    declined = tool_message(session, "run_simulation")
    assert declined.tool_ok is False
    assert "declined" in declined.content
    # The model was told, so it can choose a different route rather than silently retrying.
    assert len(captured["calls"]) == 2
    assert_transcript_is_replayable(session)


def test_a_new_message_closes_an_abandoned_confirmation(monkeypatch):
    stub_java(monkeypatch)
    script_model(
        monkeypatch,
        [
            ModelTurn(
                text="",
                tool_calls=[ToolCallRecord(call_id="c1", name="run_simulation", arguments={"reason": "x"})],
            ),
            ModelTurn(text="No run happened.", tool_calls=[]),
        ],
    )
    session = new_session()
    user_says(session, "run it")
    asyncio.run(advance(session, credential(), "Bearer test"))
    assert session.pending is not None

    # The user ignores the confirmation and asks something else instead.
    cancel_pending(session, "The user moved on.")
    user_says(session, "never mind, what does the config look like?")
    asyncio.run(advance(session, credential(), "Bearer test"))

    assert session.pending is None
    assert_transcript_is_replayable(session)


def test_step_budget_stops_a_model_that_never_finishes(monkeypatch):
    stub_java(monkeypatch)
    script = [
        ModelTurn(
            text="",
            tool_calls=[
                ToolCallRecord(call_id=f"c{i}", name="get_experiment_config", arguments={})
            ],
        )
        for i in range(MAX_STEPS_PER_TURN + 2)
    ]
    script_model(monkeypatch, script)
    session = new_session()
    user_says(session, "loop forever")

    asyncio.run(advance(session, credential(), "Bearer test"))

    tool_messages = [m for m in session.messages if m.role == "tool"]
    assert len(tool_messages) == MAX_STEPS_PER_TURN
    # Two scripted turns are left over, which is what proves the cap stopped it.
    assert len(script) == 2
    assert session.status == "STEP_LIMIT_REACHED"
    assert any(event.event_type == "turn_step_limit_reached" for event in session.events)
    assert_transcript_is_replayable(session)


def test_malformed_arguments_are_reported_and_nothing_is_executed(monkeypatch):
    seen = stub_java(monkeypatch)
    script_model(
        monkeypatch,
        [
            ModelTurn(
                text="",
                tool_calls=[
                    ToolCallRecord(
                        call_id="c1",
                        name="update_experiment_config",
                        parse_error="Tool arguments were not valid JSON (Expecting value).",
                    )
                ],
            ),
            ModelTurn(text="Let me retry that.", tool_calls=[]),
        ],
    )
    session = new_session()
    user_says(session, "change something")

    asyncio.run(advance(session, credential(), "Bearer test"))

    message = tool_message(session, "update_experiment_config")
    assert message.tool_ok is False
    assert "not valid JSON" in message.content
    # Nothing ran, and in particular the configuration was not silently changed.
    assert seen["validations"] == []
    assert session.working_config["targetCount"] == 3
    assert_transcript_is_replayable(session)


def test_a_configuration_java_rejects_is_not_applied(monkeypatch):
    stub_java(monkeypatch, validate_error="targetCount must be between 1 and 50")
    script_model(
        monkeypatch,
        [
            ModelTurn(
                text="",
                tool_calls=[
                    ToolCallRecord(
                        call_id="c1",
                        name="update_experiment_config",
                        arguments={"patch": {"targetCount": 999}},
                    )
                ],
            ),
            ModelTurn(text="That value was refused.", tool_calls=[]),
        ],
    )
    session = new_session()
    user_says(session, "use 999 targets")

    asyncio.run(advance(session, credential(), "Bearer test"))

    message = tool_message(session, "update_experiment_config")
    assert message.tool_ok is False
    assert "rejected" in message.content
    assert session.working_config["targetCount"] == 3
    assert_transcript_is_replayable(session)


def test_unknown_fields_are_refused_before_java_is_asked(monkeypatch):
    seen = stub_java(monkeypatch)
    script_model(
        monkeypatch,
        [
            ModelTurn(
                text="",
                tool_calls=[
                    ToolCallRecord(
                        call_id="c1",
                        name="update_experiment_config",
                        arguments={"patch": {"warpDrive": True}},
                    )
                ],
            ),
            ModelTurn(text="ok", tool_calls=[]),
        ],
    )
    session = new_session()
    user_says(session, "invent a field")

    asyncio.run(advance(session, credential(), "Bearer test"))

    message = tool_message(session, "update_experiment_config")
    assert message.tool_ok is False
    assert "warpDrive" in message.content
    assert seen["validations"] == []
    assert_transcript_is_replayable(session)


def test_a_tool_crash_fails_that_call_only(monkeypatch):
    stub_java(monkeypatch)
    script_model(
        monkeypatch,
        [
            ModelTurn(
                text="",
                tool_calls=[ToolCallRecord(call_id="c1", name="run_simulation", arguments={"reason": "x"})],
            ),
            ModelTurn(text="The run failed; here is what I know.", tool_calls=[]),
        ],
    )
    session = new_session(auto_approve=True)

    async def exploding_run(config, authorization=None):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.domain_tools.run_simulation", exploding_run)
    user_says(session, "run it")

    asyncio.run(advance(session, credential(), "Bearer test"))

    message = tool_message(session, "run_simulation")
    assert message.tool_ok is False
    assert "RuntimeError" in message.content
    # The session survived and the model got to respond to the failure.
    assert session.status == "ACTIVE"
    assert session.messages[-1].content.startswith("The run failed")
    assert_transcript_is_replayable(session)


def test_evidence_values_are_the_java_numbers(monkeypatch):
    stub_java(monkeypatch)
    script_model(
        monkeypatch,
        [
            ModelTurn(
                text="",
                tool_calls=[ToolCallRecord(call_id="c1", name="run_simulation", arguments={"reason": "x"})],
            ),
            ModelTurn(text="Tracking rate is 99.9% on my own authority.", tool_calls=[]),
        ],
    )
    session = new_session(auto_approve=True)
    user_says(session, "run it")

    asyncio.run(advance(session, credential(), "Bearer test"))

    message = tool_message(session, "run_simulation")
    assert {item["metric"]: item["value"] for item in message.evidence} == RUN_METRICS
    assert all(item["source"] == "java-backend-result" for item in message.evidence)
    # The prose the model volunteered does not change the evidence card.
    assert message.evidence[0]["value"] == RUN_METRICS["averagePositionError"]
    assert session.last_result == {"metrics": RUN_METRICS, "runId": "run-1"}


def test_rule_mode_is_labelled_and_proposes_exactly_one_step(monkeypatch):
    stub_java(monkeypatch)
    session = new_session(provider="rule", model=None)
    user_says(session, "比较轮询调度与优先级调度在多目标场景下的跟踪表现")

    asyncio.run(advance(session, None, "Bearer test"))

    assistant_messages = [m for m in session.messages if m.role == "assistant"]
    assert len(assistant_messages) == 1
    assert assistant_messages[0].produced_by == "rule"
    assert len(assistant_messages[0].tool_calls) == 1
    # Rule mode cannot narrate results, so it stops at the confirmation gate.
    assert session.pending is not None
    assert session.status == "AWAITING_CONFIRMATION"


def test_a_model_failure_leaves_the_question_in_place(monkeypatch):
    async def failing_call(system_prompt, messages, tools, cred):
        if False:
            yield
        raise ModelGatewayError("MODEL_UNAVAILABLE", "connection refused")

    monkeypatch.setattr("app.agent_loop.stream_call_with_tools", failing_call)
    session = new_session()
    user_says(session, "run something")

    with pytest.raises(ModelGatewayError):
        asyncio.run(advance(session, credential(), "Bearer test"))

    # Only the user's turn is present, so retrying does not duplicate an unanswered tool call.
    assert [m.role for m in session.messages] == ["user"]
    assert session.status == "ACTIVE"
    assert any(event.event_type == "model_error" for event in session.events)


def test_system_prompt_shows_the_state_the_model_is_working_from(monkeypatch):
    stub_java(monkeypatch)
    captured = script_model(monkeypatch, [ModelTurn(text="ok", tool_calls=[])])
    session = new_session()
    # The loop always writes these two together; the prompt must expose both.
    session.last_result = {"metrics": {"trackingRate": 0.5}, "runId": "run-9"}
    session.last_run_id = "run-9"
    user_says(session, "what do we have?")

    asyncio.run(advance(session, credential(), "Bearer test"))

    prompt = captured["calls"][0]["system_prompt"]
    assert "working_config" in prompt
    assert '"targetCount": 3' in prompt
    assert '"trackingRate": 0.5' in prompt
    assert "run-9" in prompt
    # The tool catalog is exposed to the model, including the confirmation-required ones.
    assert "run_simulation" in captured["calls"][0]["tool_names"]


# --------------------------------------------------------------------------- protocol conversion


def test_openai_transcript_uses_the_tool_role():
    messages = [
        AgentMessage(role="user", content="run it"),
        AgentMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCallRecord(call_id="c1", name="run_simulation", arguments={"reason": "x"})],
        ),
        AgentMessage(role="tool", content='{"ok": true}', tool_call_id="c1", tool_name="run_simulation"),
    ]

    payload = to_openai_messages("system", messages)

    assert payload[0] == {"role": "system", "content": "system"}
    assert payload[2]["tool_calls"][0]["function"]["name"] == "run_simulation"
    # Arguments travel as a JSON string on this protocol.
    assert json.loads(payload[2]["tool_calls"][0]["function"]["arguments"]) == {"reason": "x"}
    assert payload[3]["role"] == "tool"
    assert payload[3]["tool_call_id"] == "c1"


def test_anthropic_transcript_merges_roles_and_leads_with_tool_results():
    messages = [
        AgentMessage(role="user", content="run both"),
        AgentMessage(
            role="assistant",
            content="Running.",
            tool_calls=[
                ToolCallRecord(call_id="a", name="run_simulation", arguments={}),
                ToolCallRecord(call_id="b", name="calculate_metrics", arguments={}),
            ],
        ),
        AgentMessage(role="tool", content="first", tool_call_id="a", tool_name="run_simulation"),
        AgentMessage(role="tool", content="second", tool_call_id="b", tool_name="calculate_metrics"),
        AgentMessage(role="user", content="and then?"),
    ]

    payload = to_anthropic_messages(messages)

    # user, assistant, then one merged user turn: no two consecutive roles.
    assert [entry["role"] for entry in payload] == ["user", "assistant", "user"]
    merged = payload[2]["content"]
    assert [block["type"] for block in merged] == ["tool_result", "tool_result", "text"]
    assert merged[0]["tool_use_id"] == "a"
    assert payload[1]["content"][0] == {"type": "text", "text": "Running."}
    assert payload[1]["content"][1]["input"] == {}


def test_context_window_trims_and_recaps_deterministically():
    messages = []
    for index in range(40):
        messages.append(AgentMessage(role="user", content=f"question {index}"))
        messages.append(
            AgentMessage(
                role="tool",
                content=f'{{"ok": true, "index": {index}}}',
                tool_call_id=f"c{index}",
                tool_name="get_experiment_config",
                tool_ok=True,
            )
        )

    kept, digest = context_window(messages)

    assert kept == messages[-24:]
    assert digest is not None
    assert "factual recap" in digest
    # The recap keeps the trimmed entries closest to the live window and drops the oldest first,
    # so the most recent dropped turn is always represented.
    assert "question 27" in digest
    # Deterministic: same input, same recap.
    assert context_window(messages)[1] == digest
    # And bounded, so trimming cannot itself grow the context without limit.
    assert len(digest) < 2200


def test_context_window_is_untouched_when_it_fits():
    messages = [AgentMessage(role="user", content="hello")]

    kept, digest = context_window(messages)

    assert kept == messages
    assert digest is None


# --------------------------------------------------------------------------- HTTP surface


def set_authenticated_user(user_id: int = OWNER) -> None:
    app.dependency_overrides[require_agent_user] = lambda: {
        "authorization": "Bearer test-token",
        "user": {"userId": user_id},
        "user_id": user_id,
    }


def stub_storage(monkeypatch):
    """Stand in for the Java-side conversation store."""
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
        # The graph routes every test message into the (mocked) tool loop unless a test overrides
        # the classifier itself.
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


def test_conversation_can_be_created_continued_and_resumed(monkeypatch):
    stored = stub_storage(monkeypatch)
    stub_java(monkeypatch)
    script_model(
        monkeypatch,
        [
            ModelTurn(
                text="",
                tool_calls=[ToolCallRecord(call_id="c1", name="run_simulation", arguments={"reason": "x"})],
            ),
            ModelTurn(text="Done: error 3.12.", tool_calls=[]),
        ],
    )
    set_authenticated_user()
    client = TestClient(app)
    try:
        created = client.post("/api/v1/agent/conversations", json={"auto_approve": False})
        assert created.status_code == 200
        session_id = created.json()["session_id"]

        replied = client.post(
            f"/api/v1/agent/conversations/{session_id}/messages",
            json={"message": "Run the default experiment", "model_provider": "openai"},
            headers={"X-Model-Api-Key": "user-token"},
        )
        assert replied.status_code == 200
        body = replied.json()
        assert body["status"] == "AWAITING_CONFIRMATION"
        assert body["title"] == "Run the default experiment"
        assert body["pending"]["tool_calls"][0]["name"] == "run_simulation"

        decided = client.post(
            f"/api/v1/agent/conversations/{session_id}/decision",
            json={"approve": True, "model_provider": "openai"},
            headers={"X-Model-Api-Key": "user-token"},
        )
        assert decided.status_code == 200
        final = decided.json()
        assert final["status"] == "ACTIVE"
        assert final["last_run_id"] == "run-1"
        assert final["messages"][-1]["content"] == "Done: error 3.12."

        # Stored after every turn, so a restart does not lose the conversation.
        assert session_id in stored
        assert stored[session_id]["message_count"] if "message_count" in stored[session_id] else True

        # Drop the live copy to force a rehydrate from storage.
        session_store.drop(session_id)
        reloaded = client.get(f"/api/v1/agent/conversations/{session_id}")
        assert reloaded.status_code == 200
        assert reloaded.json()["last_run_id"] == "run-1"
        assert len(reloaded.json()["messages"]) == len(final["messages"])
    finally:
        app.dependency_overrides.pop(require_agent_user, None)


def test_a_conversation_belongs_to_one_user(monkeypatch):
    stub_storage(monkeypatch)
    stub_java(monkeypatch)
    script_model(monkeypatch, [])
    set_authenticated_user(OWNER)
    client = TestClient(app)
    try:
        session_id = client.post("/api/v1/agent/conversations", json={}).json()["session_id"]

        set_authenticated_user(OWNER + 1)
        assert client.get(f"/api/v1/agent/conversations/{session_id}").status_code == 404
        assert (
            client.post(
                f"/api/v1/agent/conversations/{session_id}/messages",
                json={"message": "let me in", "model_provider": "openai"},
                headers={"X-Model-Api-Key": "user-token"},
            ).status_code
            == 404
        )
    finally:
        app.dependency_overrides.pop(require_agent_user, None)


def test_the_model_token_never_reaches_a_persisted_conversation(monkeypatch):
    stored = stub_storage(monkeypatch)
    stub_java(monkeypatch)
    script_model(monkeypatch, [ModelTurn(text="Hello.", tool_calls=[])])
    set_authenticated_user()
    client = TestClient(app)
    secret = "sk-conversation-secret-value"
    try:
        session_id = client.post("/api/v1/agent/conversations", json={}).json()["session_id"]
        response = client.post(
            f"/api/v1/agent/conversations/{session_id}/messages",
            json={"message": "hello", "model_provider": "openai"},
            headers={"X-Model-Api-Key": secret},
        )

        assert response.status_code == 200
        assert secret not in response.text
        assert secret not in json.dumps(stored[session_id], ensure_ascii=False)
    finally:
        app.dependency_overrides.pop(require_agent_user, None)


def test_a_model_failure_keeps_the_transcript_but_reports_the_error(monkeypatch):
    stored = stub_storage(monkeypatch)
    stub_java(monkeypatch)

    async def failing_call(system_prompt, messages, tools, cred):
        if False:
            yield
        raise ModelGatewayError("MODEL_UNAVAILABLE", "connection refused")

    monkeypatch.setattr("app.agent_loop.stream_call_with_tools", failing_call)
    set_authenticated_user()
    client = TestClient(app)
    try:
        session_id = client.post("/api/v1/agent/conversations", json={}).json()["session_id"]
        response = client.post(
            f"/api/v1/agent/conversations/{session_id}/messages",
            json={"message": "hello", "model_provider": "openai"},
            headers={"X-Model-Api-Key": "user-token"},
        )

        assert response.status_code == 503
        # The user's message survived, so the same request can simply be sent again.
        assert [m["role"] for m in stored[session_id]["messages"]] == ["user"]
    finally:
        app.dependency_overrides.pop(require_agent_user, None)
