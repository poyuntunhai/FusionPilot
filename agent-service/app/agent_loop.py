"""
The multi-turn tool-calling loop.

Shape of one turn: the user's message is appended, then the model is asked for its next step. If it
asks for tools they are executed and their results go back to the model, which is asked again.
The turn ends when the model replies without asking for a tool, when a destructive tool needs the
user's approval, or when the per-turn step budget runs out.

Two behaviours are deliberate rather than incidental:

* **A confirmation gate on tools that spend resources.** The batch is held whole, because pausing
  mid-batch would leave tool calls in the transcript that never received a result, and both
  providers reject a transcript shaped like that.
* **A per-turn step budget.** Without one, a model that keeps calling the same tool would run until
  the token budget or the user's patience gives out. Hitting the cap is reported, not hidden.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from .conversation import (
    AgentMessage,
    ToolCallRecord,
    assistant_message,
    context_window,
    last_user_text,
    now_iso,
    pending_tool_calls,
    tool_result_message,
)
from .domain_tools import (
    CONFIG_SUMMARY_KEYS,
    ToolContext,
    ToolOutcome,
    describe_pending,
    execute_tool,
    needs_confirmation,
    tool_schemas_for_model,
)
from .model_gateway import ModelCredential, ModelGatewayError, stream_call_with_tools
from .models import AgentSession, PendingDecision, PlanRequest
from .model_planner import merge_experiment_config
from .rules import build_plan


MAX_STEPS_PER_TURN = 6

EventSink = Callable[[str, dict[str, Any]], None]


SYSTEM_PROMPT = """You are the simulation copilot inside FusionPilot, a radar and
electronic-countermeasure simulation platform. You work with the user across several turns to
design experiments, run them, and read the results.

How you work:
- You act through tools. When the user wants a result, call the tool that produces it rather than
  describing what could be done.
- Read the current configuration before changing it, and change only the fields the user asked
  about. Every change is checked by the Java core through the update tool.
- run_simulation and compare_scheduling_policies need the user's approval. State in one sentence
  what the run is for; the user sees your call and approves or declines it.
- After a tool returns, give a short reading of what the numbers show. Prefer two or three
  sentences over a report unless the user asks for detail.

Hard rules:
- The Java simulation core is the only source of truth for results. Never state a metric value
  that no tool returned in this conversation, and never fill a gap by estimating.
- The simulation is deterministic for a fixed random seed: the same configuration and seed always
  reproduce bit-for-bit identical metrics. Identical numbers across two runs do NOT mean the
  result was cached or that the configuration was ignored. Each run has its own fresh run id, and
  the run's own config summary reports the configuration that was actually used. To check whether
  a change took effect, compare the run's config summary or change a value that must move a metric
  (e.g. availableResources changes waiting time), never assume caching from equal numbers alone.
- Never invent metric names, configuration fields, or target positions.
- If a tool fails, say so plainly and continue from what you actually know.
- Reply in the same language the user writes in."""


def emit_into(session: AgentSession, on_event: EventSink | None = None) -> EventSink:
    """
    Record an event, and hand it to a live consumer if there is one.

    Every step already produced an event for the persisted trail. Passing the same event straight
    to the caller is what makes streaming work without a second, parallel notion of "progress":
    the stream and the stored trail cannot disagree because they are the same list of events.

    This is shared by the tool loop and the LangGraph orchestration layer, so routing events
    (``intent_classified``, ``clarification_requested``) are persisted exactly like tool events.
    """

    def emit(event_type: str, payload: dict[str, Any]) -> None:
        from .models import TraceEvent
        from uuid import uuid4

        # Token deltas are streamed to a live consumer but never persisted: a long reply would
        # otherwise add one event per token to the stored trail, bloating every snapshot.
        if event_type != "token":
            session.events.append(
                TraceEvent(
                    event_id=str(uuid4()),
                    trace_id=session.session_id,
                    event_type=event_type,
                    payload=payload,
                    created_at=now_iso(),
                )
            )
        if on_event is not None:
            on_event(event_type, payload)

    return emit


def build_system_prompt(
    session: AgentSession,
    digest: str | None,
    steps_remaining: int,
) -> str:
    """
    Assemble the system prompt for one call.

    The session state is spelled out on every call rather than being left implicit in the
    transcript, so what the model is working from is inspectable at the point it matters.
    """
    working = {key: session.working_config.get(key) for key in CONFIG_SUMMARY_KEYS if key in session.working_config}
    sections = [SYSTEM_PROMPT]

    if session.memory.strip():
        sections.append(
            "\n## Long-term memory about this user\n" + session.memory.strip()
            + "\nUse this for continuity; it may be stale, so prefer what the tools return when they conflict."
        )

    state = [
        "\n## Session state",
        f"working_config = {json.dumps(working, ensure_ascii=False)}",
    ]
    if session.last_result and session.last_result.get("metrics"):
        state.append(f"last_run_metrics = {json.dumps(session.last_result['metrics'], ensure_ascii=False)}")
        if session.last_run_id:
            state.append(f"last_run_id = {session.last_run_id}")
    else:
        state.append("No run has happened in this session yet, so there are no results to quote.")
    state.append(f"Tool steps remaining in this turn: {max(0, steps_remaining)}.")
    sections.append("\n".join(state))

    if digest:
        sections.append("\n## Trimmed earlier turns\n" + digest)

    return "\n".join(sections)


async def advance(
    session: AgentSession,
    credential: ModelCredential | None,
    authorization: str | None,
    on_event: EventSink | None = None,
) -> AgentSession:
    """Run the loop until it stops, pauses for approval, or hits the per-turn step budget."""
    emit = emit_into(session, on_event)
    if credential is None:
        await _advance_rule_mode(session, authorization, emit)
    else:
        await _advance_model_mode(session, credential, authorization, emit)
    session.updated_at = now_iso()
    return session


async def _advance_model_mode(
    session: AgentSession,
    credential: ModelCredential,
    authorization: str | None,
    emit: EventSink,
) -> None:
    for depth in range(1, MAX_STEPS_PER_TURN + 1):
        kept, digest = context_window(session.messages)
        system_prompt = build_system_prompt(session, digest, MAX_STEPS_PER_TURN - depth + 1)
        try:
            text_parts: list[str] = []
            tool_calls = []
            async for event in stream_call_with_tools(
                system_prompt,
                kept,
                tool_schemas_for_model(),
                credential,
            ):
                if event.kind == "text":
                    text_parts.append(event.text)
                    emit("token", {"text": event.text})
                elif event.kind == "tool_calls":
                    tool_calls = event.tool_calls or []
        except ModelGatewayError as exc:
            emit("model_error", {"code": exc.code, "message": exc.message})
            session.status = "ACTIVE"
            raise

        message = assistant_message("".join(text_parts), tool_calls)
        message.produced_by = f"{credential.provider}:{credential.model}"
        session.messages.append(message)
        emit(
            "assistant_message",
            {
                "has_text": bool(message.content),
                "tool_names": [call.name for call in tool_calls],
                "step": depth,
            },
        )

        if not tool_calls:
            session.status = "ACTIVE"
            emit("turn_completed", {"steps": depth})
            return

        if any(needs_confirmation(call.name) for call in tool_calls) and not session.auto_approve:
            session.pending = _pending_from(tool_calls)
            session.status = "AWAITING_CONFIRMATION"
            emit(
                "confirmation_requested",
                {
                    "tool_names": [call.name for call in tool_calls],
                    "prompt": session.pending.prompt,
                },
            )
            return

        await _execute_batch(session, tool_calls, authorization, emit)

    # The budget ran out with the model still wanting to act. Reported so the user can see the
    # turn was cut short instead of wondering why the agent went quiet.
    session.status = "STEP_LIMIT_REACHED"
    emit(
        "turn_step_limit_reached",
        {"limit": MAX_STEPS_PER_TURN},
    )


async def _advance_rule_mode(
    session: AgentSession,
    authorization: str | None,
    emit: EventSink,
) -> None:
    """
    Deterministic single-step handling used when no model credential is available.

    This is not a multi-turn agent and does not pretend to be one: it plans with the local rule
    planner, proposes exactly one tool, and stops. The UI labels the turn as rule-produced.
    """
    goal = _last_user_text(session)
    if not goal:
        session.status = "ACTIVE"
        return

    base_config = session.working_config or session.default_config
    request = PlanRequest(goal=goal)
    plan = build_plan(request, base_config)
    session.plan = plan
    emit("plan_created", {"planner": "rule", "recommended_tool": plan.recommended_tool})

    merged = merge_experiment_config(base_config, plan.experiment_config, request)
    session.working_config = merged

    tool_name = plan.recommended_tool or "run_simulation"
    call = ToolCallRecord(call_id=f"rule_{len(session.messages)}", name=tool_name, arguments={})
    message = assistant_message(
        f"{plan.title}. {plan.planning_note or ''}".strip(),
        [call],
    )
    message.produced_by = "rule"
    session.messages.append(message)
    emit("assistant_message", {"has_text": True, "tool_names": [tool_name], "step": 1})

    if needs_confirmation(tool_name) and not session.auto_approve:
        session.pending = _pending_from([call])
        session.status = "AWAITING_CONFIRMATION"
        emit("confirmation_requested", {"tool_names": [tool_name], "prompt": session.pending.prompt})
        return

    await _execute_batch(session, [call], authorization, emit)
    session.status = "ACTIVE"
    emit("turn_completed", {"steps": 1, "planner": "rule"})


def _pending_from(calls: list[ToolCallRecord]) -> PendingDecision:
    prompts = [describe_pending(call.name, call.arguments) for call in calls]
    return PendingDecision(
        tool_calls=calls,
        prompt=" ".join(prompts),
        created_at=now_iso(),
    )


async def _execute_batch(
    session: AgentSession,
    calls: list[ToolCallRecord],
    authorization: str | None,
    emit: EventSink,
) -> None:
    context = ToolContext(
        working_config=dict(session.working_config),
        default_config=dict(session.default_config),
        last_result=session.last_result,
        last_run_id=session.last_run_id,
    )
    for call in calls:
        if call.parse_error:
            # Never executed: running a tool with silently-emptied arguments would look like a
            # successful call with no effect.
            outcome = ToolOutcome(
                ok=False,
                error=(
                    f"The arguments for {call.name} could not be read: {call.parse_error} "
                    "Re-issue the call with valid JSON."
                ),
            )
            emit("tool_failed", {"tool_name": call.name, "error": outcome.error, "stage": "arguments"})
        else:
            emit("tool_called", {"tool_name": call.name, "arguments": call.arguments})
            try:
                outcome = await execute_tool(call.name, call.arguments, context, authorization)
            except Exception as exc:  # noqa: BLE001 - a tool crash must not kill the session
                outcome = ToolOutcome(ok=False, error=f"{call.name} raised {type(exc).__name__}: {exc}")

        result_message = tool_result_message(
            call,
            outcome.ok,
            outcome.as_model_content(),
            outcome.evidence,
            outcome.limitations,
            outcome.run_id,
        )
        session.messages.append(result_message)
        session.tool_call_count += 1

        if outcome.evidence:
            session.last_evidence = outcome.evidence
            session.last_limitations = outcome.limitations
        if outcome.run_id:
            session.last_run_id = outcome.run_id
        emit(
            "tool_result",
            {
                "tool_name": call.name,
                "ok": outcome.ok,
                "error": outcome.error,
                "run_id": outcome.run_id,
                "evidence_count": len(outcome.evidence),
            },
        )

    session.working_config = context.working_config
    session.last_result = context.last_result
    session.last_run_id = context.last_run_id


async def resolve_decision(
    session: AgentSession,
    approve: bool,
    credential: ModelCredential | None,
    authorization: str | None,
    on_event: EventSink | None = None,
) -> AgentSession:
    """Answer the outstanding confirmation, then let the loop continue from there."""
    emit = emit_into(session, on_event)
    pending = session.pending
    session.pending = None
    if pending is None:
        emit("decision_ignored", {"reason": "No tool call was waiting for a decision."})
        return await advance(session, credential, authorization, on_event)

    if approve:
        emit("confirmation_received", {"tool_names": [call.name for call in pending.tool_calls]})
        await _execute_batch(session, pending.tool_calls, authorization, emit)
    else:
        for call in pending.tool_calls:
            session.messages.append(
                tool_result_message(
                    call,
                    False,
                    json.dumps(
                        {
                            "ok": False,
                            "error": (
                                "The user declined to run this tool. Do not call it again unless they "
                                "ask you to; suggest an alternative or ask what to change."
                            ),
                        }
                    ),
                )
            )
        emit("confirmation_declined", {"tool_names": [call.name for call in pending.tool_calls]})

    return await advance(session, credential, authorization, on_event)


def cancel_pending(session: AgentSession, reason: str, on_event: EventSink | None = None) -> None:
    """
    Clear an unanswered confirmation.

    A transcript only replays cleanly when every requested call has a result, so an abandoned
    confirmation is closed out with a result of its own before anything new is appended.
    """
    emit = emit_into(session, on_event)
    unanswered = pending_tool_calls(session.messages)
    if not unanswered:
        session.pending = None
        return
    for call in unanswered:
        session.messages.append(
            tool_result_message(
                call,
                False,
                json.dumps({"ok": False, "error": reason}),
            )
        )
    session.pending = None
    emit("confirmation_cancelled", {"tool_names": [call.name for call in unanswered]})


def _last_user_text(session: AgentSession) -> str:
    return last_user_text(session.messages)
