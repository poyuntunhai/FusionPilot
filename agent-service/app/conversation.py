"""
Provider-neutral conversation state for the multi-turn agent.

The session transcript is stored in one neutral shape and converted to the provider's wire
format at call time. That is deliberate: it is what lets a conversation started on one provider
continue on another without rewriting history, and it keeps the persisted session readable
regardless of which model produced it.

Two protocol families are supported here:

* ``openai``     - chat completions with ``tools`` / ``tool_calls`` (OpenAI, DeepSeek, Qwen, Zhipu)
* ``anthropic``  - messages API with ``tool_use`` / ``tool_result`` content blocks

They disagree on more than field names, and the differences are load-bearing:

* OpenAI puts tool calls on the assistant message and results in ``role: "tool"`` entries.
  Anthropic has no ``tool`` role: results travel inside a *user* message as content blocks.
* Anthropic rejects consecutive same-role messages, so runs must be merged.
* Anthropic requires ``tool_result`` blocks to lead the user message they appear in.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolCallRecord(BaseModel):
    """One tool invocation the model asked for."""

    call_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Set when the provider returned arguments that are not valid JSON. The call is not executed;
    # the model is told what went wrong so it can re-issue the call instead of the failure being
    # swallowed as "the tool ran with no arguments".
    parse_error: str | None = None


class AgentMessage(BaseModel):
    """
    One entry in the transcript.

    Tool results keep their deterministic evidence alongside the text that is sent back to the
    model, so the UI can show Java-sourced numbers without asking the model to restate them.
    """

    message_id: str = Field(default_factory=lambda: str(uuid4()))
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_ok: bool | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    run_id: str | None = None
    # The knowledge sections an answer was grounded in, as {chunk_id, doc, title, score}. Kept on
    # the message rather than only in the event stream so the transcript still shows its sources
    # when a conversation is reloaded from storage.
    knowledge: list[dict[str, Any]] = Field(default_factory=list)
    # Which agent produced an assistant turn: the model label, or "rule" when the local rule
    # planner answered. The UI labels rule turns so deterministic text is never mistaken for a
    # model's reasoning.
    produced_by: str | None = None
    created_at: str = Field(default_factory=now_iso)


def tool_result_message(
    call: ToolCallRecord,
    ok: bool,
    content: str,
    evidence: list[dict[str, Any]] | None = None,
    limitations: list[str] | None = None,
    run_id: str | None = None,
) -> AgentMessage:
    return AgentMessage(
        role="tool",
        content=content,
        tool_call_id=call.call_id,
        tool_name=call.name,
        tool_ok=ok,
        evidence=evidence or [],
        limitations=limitations or [],
        run_id=run_id,
    )


def assistant_message(text: str | None, tool_calls: list[ToolCallRecord]) -> AgentMessage:
    return AgentMessage(role="assistant", content=(text or "").strip(), tool_calls=tool_calls)


def assistant_tool_ids(messages: list[AgentMessage]) -> set[str]:
    return {call.call_id for message in messages for call in message.tool_calls}


def last_user_text(messages: list[AgentMessage]) -> str:
    """The most recent user utterance, or an empty string if none has been made."""
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return ""


def pending_tool_calls(messages: list[AgentMessage]) -> list[ToolCallRecord]:
    """
    Tool calls the model asked for that never received a result.

    A transcript only replays cleanly if every requested call has an answer, so the loop resolves
    these before appending anything new.
    """
    answered = {message.tool_call_id for message in messages if message.role == "tool"}
    return [
        call
        for message in messages
        if message.role == "assistant"
        for call in message.tool_calls
        if call.call_id not in answered
    ]


# --------------------------------------------------------------------------- context management

CONTEXT_WINDOW_MESSAGES = 24
DIGEST_CHAR_BUDGET = 1600


def context_window(messages: list[AgentMessage]) -> tuple[list[AgentMessage], str | None]:
    """
    Trim the transcript to a bounded window, with a deterministic digest of what was dropped.

    Older entries are replaced by a factual recap rather than being silently forgotten, and the
    recap is built from stored data only - no extra model call is made to summarise, so trimming
    costs nothing and is reproducible for a given transcript.
    """
    if len(messages) <= CONTEXT_WINDOW_MESSAGES:
        return messages, None

    dropped = messages[: len(messages) - CONTEXT_WINDOW_MESSAGES]
    kept = messages[len(messages) - CONTEXT_WINDOW_MESSAGES :]

    lines: list[str] = []
    for message in dropped:
        if message.role == "user":
            lines.append(f"- user asked: {_shorten(message.content, 90)}")
        elif message.role == "assistant":
            if message.content:
                lines.append(f"- you replied: {_shorten(message.content, 90)}")
            for call in message.tool_calls:
                lines.append(f"- you called {call.name}({_shorten(json.dumps(call.arguments, ensure_ascii=False), 90)})")
        else:
            status = "ok" if message.tool_ok else "failed"
            lines.append(f"- {message.tool_name} {status}: {_shorten(message.content, 110)}")

    while lines and sum(len(line) + 1 for line in lines) > DIGEST_CHAR_BUDGET:
        lines.pop(0)

    digest = (
        "Earlier turns have been trimmed to stay inside the context window. "
        "This is a factual recap of the trimmed range, not a model summary:\n" + "\n".join(lines)
    )
    return kept, digest


def _shorten(value: str, limit: int) -> str:
    flat = " ".join((value or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "\u2026"


# --------------------------------------------------------------------------- provider conversion


def to_openai_messages(system_prompt: str, messages: list[AgentMessage]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for message in messages:
        if message.role == "user":
            payload.append({"role": "user", "content": message.content})
        elif message.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.call_id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                    for call in message.tool_calls
                ]
            payload.append(entry)
        else:
            payload.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content or "",
                }
            )
    return payload


def to_anthropic_messages(messages: list[AgentMessage]) -> list[dict[str, Any]]:
    """
    Build the Anthropic message array.

    Same-role runs are merged because the API rejects them, and every ``tool_result`` block is
    placed at the front of its user message as required.
    """
    raw: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "assistant":
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.call_id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            raw.append({"role": "assistant", "content": blocks})
        elif message.role == "tool":
            raw.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id,
                            "content": message.content or "",
                        }
                    ],
                }
            )
        else:
            raw.append({"role": "user", "content": [{"type": "text", "text": message.content}]})

    merged: list[dict[str, Any]] = []
    for entry in raw:
        if merged and merged[-1]["role"] == entry["role"]:
            merged[-1]["content"] = _merge_blocks(merged[-1]["content"], entry["content"])
        else:
            merged.append({"role": entry["role"], "content": list(entry["content"])})
    return merged


def _merge_blocks(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = [block for block in left if block["type"] == "tool_result"]
    others = [block for block in left if block["type"] != "tool_result"]
    incoming_results = [block for block in right if block["type"] == "tool_result"]
    incoming_others = [block for block in right if block["type"] != "tool_result"]
    # Tool results must come first inside a user message, so they are not simply appended.
    return results + incoming_results + others + incoming_others
