"""
Long-term memory distillation.

After a turn, the agent reflects on what happened and updates the user's persistent note. This is
the "memory" half of the agent: it lets a new conversation resume from accumulated preferences and
findings instead of starting cold. The distillation is best-effort - a failed model call never
blocks the main flow.
"""
from __future__ import annotations

import json

from .model_gateway import ModelCredential, complete
from .models import AgentSession


MEMORY_SYSTEM_PROMPT = """You are the long-term memory module of FusionPilot, a radar and
electronic-countermeasure simulation platform. You keep a short persistent note about each user so
future conversations can continue from context.

Distill only durable facts worth remembering:
- the user's preferences and habits (target counts, fusion methods, scheduling policies they reach for)
- stable findings from this domain (which fusion method or policy won, under what conditions)
- conventions the user asked for.

Rules:
- Keep it terse: a few short bullet lines, at most 300 characters, in the user's language.
- Prefer facts the tools returned over anything guessed.
- Drop anything transient (a single random seed's numbers, ephemeral errors, exact run ids).
- Output only the updated note text. No preamble, no markdown fences."""


def transcript_summary(session: AgentSession) -> str:
    """A compact, factual recap of the conversation so far, for the distiller."""
    lines: list[str] = []
    for message in session.messages:
        if message.role == "user":
            lines.append(f"user: {message.content.strip()}")
        elif message.role == "tool" and message.tool_name == "run_simulation":
            try:
                payload = json.loads(message.content)
                metrics = (payload.get("result") or {}).get("metrics") or {}
                config = (payload.get("result") or {}).get("config") or {}
                lines.append(
                    "run result: "
                    + json.dumps({"config": config, "metrics": metrics}, ensure_ascii=False)
                )
            except (json.JSONDecodeError, AttributeError):
                continue
        elif message.role == "assistant" and message.content:
            lines.append(f"assistant: {message.content.strip()[:200]}")
    # The tail is the most relevant; the head is covered by the persisted memory already.
    return "\n".join(lines[-24:])


async def distill(existing: str, session: AgentSession, credential: ModelCredential) -> str | None:
    """
    Produce an updated memory note, or None when there is nothing worth changing.

    Only called when a model is available; rule mode leaves the memory untouched.
    """
    summary = transcript_summary(session)
    if not summary.strip():
        return None
    messages = [
        {"role": "system", "content": MEMORY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Existing note (may be empty):\n{existing}\n\n"
                f"Recent conversation:\n{summary}\n\n"
                "Return the updated note."
            ),
        },
    ]
    updated = (await complete(messages, credential, json_mode=False)).strip()
    if not updated or updated == existing.strip():
        return None
    return updated[:1200]
