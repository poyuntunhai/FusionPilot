"""Tests for long-term memory distillation."""
import asyncio
import json

from app.conversation import AgentMessage
from app.memory import distill, transcript_summary
from app.model_gateway import ModelCredential
from app.models import AgentSession
from app.session_store import now_iso


def credential() -> ModelCredential:
    return ModelCredential(
        provider="openai",
        label="OpenAI",
        protocol="openai-compatible",
        model="gpt-4o-mini",
        api_key="sk-test",
        endpoint="http://unused",
        temperature=0.0,
        timeout_seconds=10.0,
    )


def session_with_run() -> AgentSession:
    now = now_iso()
    session = AgentSession(
        session_id="s1",
        owner_user_id=1,
        title="t",
        memory="",
        created_at=now,
        updated_at=now,
    )
    session.messages.append(AgentMessage(role="user", content="把目标数改成 5，用卡尔曼滤波跑一次"))
    run_content = json.dumps(
        {
            "ok": True,
            "result": {
                "config": {"targetCount": 5, "fusionMethod": "KALMAN_FILTER"},
                "metrics": {"averagePositionError": 1.79, "trackingRate": 1.0},
            },
        },
        ensure_ascii=False,
    )
    session.messages.append(
        AgentMessage(role="tool", tool_name="run_simulation", tool_call_id="c1", content=run_content)
    )
    return session


def test_transcript_summary_keeps_user_and_run_facts():
    summary = transcript_summary(session_with_run())
    assert "5" in summary and "卡尔曼" in summary
    assert "averagePositionError" in summary


def test_distill_returns_updated_memory(monkeypatch):
    session = session_with_run()

    async def fake_complete(messages, cred, json_mode=True):
        return "偏好 5 目标卡尔曼滤波；该项目卡尔曼误差约 1.79。"

    monkeypatch.setattr("app.memory.complete", fake_complete)

    updated = asyncio.run(distill("", session, credential()))
    assert updated is not None
    assert "卡尔曼" in updated


def test_distill_returns_none_when_model_echoes_existing(monkeypatch):
    session = session_with_run()
    existing = "偏好 5 目标卡尔曼滤波。"

    async def fake_complete(messages, cred, json_mode=True):
        return existing  # unchanged

    monkeypatch.setattr("app.memory.complete", fake_complete)

    assert asyncio.run(distill(existing, session, credential())) is None


def test_distill_returns_none_without_turns():
    session = AgentSession(
        session_id="s2",
        owner_user_id=1,
        title="t",
        created_at=now_iso(),
        updated_at=now_iso(),
    )
    assert asyncio.run(distill("", session, credential())) is None
