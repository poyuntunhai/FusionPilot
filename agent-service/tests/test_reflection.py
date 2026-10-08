"""
Tests for the self-reflection layer.

Two layers, tested separately:

* deterministic checks (pure code) — impossible metric values, evidence/metric drift
* model reflection (one call) — auditing the agent's own prose against the tool facts

The integration cases drive the whole turn graph, because the interesting behaviour is *when*
reflection runs, not just what it returns: it must skip a paused confirmation, skip a turn with no
result, and never fail the turn if the audit call itself fails.
"""

import asyncio
import json

from app.agent_graph import run_turn
from app.conversation import AgentMessage, ToolCallRecord
from app.agent_graph import EXPERIMENT, SupervisorDecision
from app.model_gateway import ModelGatewayError, ModelStreamEvent, ModelTurn, resolve_credential
from app.reflection import deterministic_self_check
from app.session_store import session_store


OWNER = 6161


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


def new_session(auto_approve=True):
    session_store.drop_for_user(OWNER)
    session = session_store.create(
        owner_user_id=OWNER,
        default_config=default_config(),
        auto_approve=auto_approve,
        provider="openai",
        model="gpt-4o-mini",
    )
    session.messages.append(AgentMessage(role="user", content="run it"))
    return session


def events_of(session) -> list[str]:
    return [event.event_type for event in session.events]


def run(session):
    return asyncio.run(run_turn(session, credential(), "Bearer test"))


def stub_experiment(monkeypatch, narrative: str):
    """Script one experiment turn: run the simulation, then say `narrative`."""
    script = [
        [ModelStreamEvent("tool_calls", tool_calls=[ToolCallRecord(call_id="c1", name="run_simulation", arguments={"reason": "x"})])],
        [ModelStreamEvent("text", text=narrative)],
    ]

    async def fake_stream(system_prompt, messages, tools_, cred):
        for event in (script.pop(0) if script else [ModelStreamEvent("text", text="done")]):
            yield event

    async def fake_run(config, authorization=None):
        return {
            "runId": "run-1",
            "config": dict(config),
            "metrics": {"averagePositionError": 3.12, "trackingRate": 0.98},
            "steps": [{"timeStep": 0}],
        }

    async def fake_classify(session, cred):
        return SupervisorDecision(EXPERIMENT, None, "test route")

    monkeypatch.setattr("app.agent_loop.stream_call_with_tools", fake_stream)
    monkeypatch.setattr("app.domain_tools.run_simulation", fake_run)
    monkeypatch.setattr("app.agent_graph.classify_intent", fake_classify)


# --------------------------------------------------------------------------- deterministic layer


def test_self_check_passes_plausible_metrics():
    session = new_session()
    session.last_result = {"metrics": {"averagePositionError": 3.12, "trackingRate": 0.98}, "runId": "r1"}
    session.last_evidence = [
        {"metric": "averagePositionError", "value": 3.12},
        {"metric": "trackingRate", "value": 0.98},
    ]
    assert deterministic_self_check(session) == []


def test_self_check_flags_an_impossible_tracking_rate():
    session = new_session()
    session.last_result = {"metrics": {"trackingRate": 1.5}, "runId": "r1"}

    issues = deterministic_self_check(session)

    assert any("trackingRate" in issue and "1.5" in issue for issue in issues)


def test_self_check_flags_a_negative_error():
    session = new_session()
    session.last_result = {"metrics": {"averagePositionError": -0.4}, "runId": "r1"}

    issues = deterministic_self_check(session)

    assert any("averagePositionError" in issue for issue in issues)


def test_self_check_flags_evidence_that_drifted_from_the_metrics():
    session = new_session()
    session.last_result = {"metrics": {"trackingRate": 0.98}, "runId": "r1"}
    session.last_evidence = [{"metric": "trackingRate", "value": 0.5}]

    issues = deterministic_self_check(session)

    assert any("不一致" in issue for issue in issues)


# --------------------------------------------------------------------------- model layer via the graph


def test_reflection_runs_and_records_a_clean_self_check(monkeypatch):
    stub_experiment(monkeypatch, "Mean position error is 3.12 with 98% tracking.")

    async def fake_reflect(messages, cred):
        return json.dumps({"supported": True, "problem": "", "correction": ""})

    monkeypatch.setattr("app.reflection.complete", fake_reflect)

    session = new_session()
    run(session)

    assert "self_check" in events_of(session)
    # A clean audit adds nothing to the transcript.
    assert all("reflect:" not in (m.produced_by or "") for m in session.messages)


def test_reflection_corrects_a_claim_the_evidence_does_not_support(monkeypatch):
    """The exact failure from before: 'identical numbers' read as 'cached'."""
    stub_experiment(monkeypatch, "两个配置结果完全一样，说明结果被缓存了。")

    async def fake_reflect(messages, cred):
        return json.dumps(
            {
                "supported": False,
                "problem": "把确定性复现误判成了缓存。",
                "correction": "相同配置与随机种子必然得到相同结果，这是确定性复现，不是缓存；判断配置是否生效要看本次 run 的 config 摘要。",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("app.reflection.complete", fake_reflect)

    session = new_session()
    run(session)

    assert "self_correction" in events_of(session)
    corrections = [m for m in session.messages if (m.produced_by or "").startswith("reflect:")]
    assert len(corrections) == 1
    assert "确定性复现" in corrections[0].content


def test_reflection_skips_when_the_turn_paused_for_approval(monkeypatch):
    stub_experiment(monkeypatch, "unused")
    called = {"reflect": False}

    async def fake_reflect(messages, cred):
        called["reflect"] = True
        return json.dumps({"supported": True, "problem": "", "correction": ""})

    monkeypatch.setattr("app.reflection.complete", fake_reflect)

    session = new_session(auto_approve=False)
    run(session)

    assert session.pending is not None
    assert "self_check" not in events_of(session)
    assert called["reflect"] is False


def test_reflection_skips_a_turn_that_produced_no_result(monkeypatch):
    script = [
        [ModelStreamEvent("tool_calls", tool_calls=[ToolCallRecord(call_id="c1", name="get_experiment_config", arguments={})])],
        [ModelStreamEvent("text", text="here is the config")],
    ]

    async def fake_stream(system_prompt, messages, tools_, cred):
        for event in (script.pop(0) if script else [ModelStreamEvent("text", text="done")]):
            yield event

    async def fake_classify(session, cred):
        return SupervisorDecision(EXPERIMENT, None, "test route")

    called = {"reflect": False}

    async def fake_reflect(messages, cred):
        called["reflect"] = True
        return json.dumps({"supported": True, "problem": "", "correction": ""})

    monkeypatch.setattr("app.agent_loop.stream_call_with_tools", fake_stream)
    monkeypatch.setattr("app.agent_graph.classify_intent", fake_classify)
    monkeypatch.setattr("app.reflection.complete", fake_reflect)

    session = new_session()
    run(session)

    assert "self_check" not in events_of(session)
    assert called["reflect"] is False


def test_a_failing_audit_does_not_fail_the_turn(monkeypatch):
    stub_experiment(monkeypatch, "Mean position error is 3.12.")

    async def failing_reflect(messages, cred):
        raise ModelGatewayError("MODEL_UNAVAILABLE", "connection refused")

    monkeypatch.setattr("app.reflection.complete", failing_reflect)

    session = new_session()
    run(session)

    # The turn still completed and the deterministic layer still reported.
    assert session.status == "ACTIVE"
    assert "self_check" in events_of(session)
    assert "self_correction" not in events_of(session)


# --------------------------------------------------------------------------- outside the graph


def test_the_approval_turn_is_audited_too(monkeypatch):
    """
    The turn *after* a confirmation approval does not go through the graph.

    ``resolve_decision`` runs the approved batch and continues in the loop, so the ``run_experiment``
    node — and its ``reflect`` edge — is never re-entered. While the check lived only inside that
    node, the one turn that reads a result the user just approved was the one turn nothing audited,
    which is precisely the turn where an overreaching claim about the result gets made. The
    evaluation suite found it; this pins it.

    The entry point is called here directly because the graph is exactly what is missing on this
    path, so a test that went through the graph would not have caught it.
    """
    from app.agent_graph import reflect_turn
    from app.agent_loop import advance, resolve_decision

    async def scenario(monkeypatch):
        calls: list[str] = []

        script = [
            [ModelStreamEvent("tool_calls", tool_calls=[ToolCallRecord(call_id="c1", name="run_simulation", arguments={"reason": "x"})])],
            [ModelStreamEvent("text", text="两次结果一样，结果被缓存了。")],
        ]

        async def fake_stream(system_prompt, messages, tools_, cred):
            for event in (script.pop(0) if script else [ModelStreamEvent("text", text="done")]):
                yield event

        async def fake_run(config, authorization=None):
            return {
                "runId": "run-1",
                "config": dict(config),
                "metrics": {"averagePositionError": 3.12, "trackingRate": 0.98},
                "steps": [{"timeStep": 0}],
            }

        async def fake_reflect(messages, cred):
            calls.append("reflect")
            return json.dumps(
                {"supported": False, "problem": "缓存误判", "correction": "这是确定性复现，不是缓存。"},
                ensure_ascii=False,
            )

        monkeypatch.setattr("app.agent_loop.stream_call_with_tools", fake_stream)
        monkeypatch.setattr("app.domain_tools.run_simulation", fake_run)
        monkeypatch.setattr("app.reflection.complete", fake_reflect)

        session = new_session(auto_approve=False)
        await advance(session, credential(), "Bearer test")
        assert session.pending is not None, "the run should have been gated"

        await resolve_decision(session, True, credential(), "Bearer test")
        # Mirrors `main.py`: the decision endpoints invoke the audit explicitly, because this turn
        # never reaches the graph node.
        await reflect_turn(session, credential())
        return session, calls

    session, calls = asyncio.run(scenario(monkeypatch))

    assert calls == ["reflect"]
    assert "self_check" in events_of(session)
    assert "self_correction" in events_of(session)
    assert any((message.produced_by or "").startswith("reflect:") for message in session.messages)
