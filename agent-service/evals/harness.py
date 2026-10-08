"""
The evaluation harness: run one case and collect everything a grader could need.

Design notes, because the choices here are the difference between a useful suite and a decoration:

* **A case is self-describing.** It carries its own scripted model, so a case is deterministic and
  does not depend on a provider's mood. The suite therefore measures *the agent given a model
  decision* — routing dispatch, the confirmation gate, tool ordering, grounding, the self-check
  layer — and not the model's judgement. Whether the model itself routes well is a separate
  question, and `--api-base` answers it by pointing the same cases at a real provider.
* **The Java core is stubbed, the HTTP surface is not.** The cases drive the real ASGI app through
  its real endpoints, so persistence, ownership, and the request/response contract are exercised.
  Only the outbound Java calls are replaced. That keeps the suite runnable with no MySQL and no
  Java process, which is what makes it usable as a regression net rather than an occasional ritual.
* **Provider calls are dispatched by prompt marker, not by order.** The scripted model answers the
  classifier / planner / reflector / memory distiller from the system prompt it is given. Consuming
  a single ordered queue would make a case's meaning depend on how many internal calls the code
  happens to make, so adding a reflection call would silently reshuffle every case.
* **Nothing here grades.** `grade.py` does that, from the recorded outcome, with no I/O and no
  model. Keeping them apart is what lets the grader be tested against deliberately broken runs.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.auth import require_agent_user
from app.agent_graph import SupervisorDecision
from app.java_client import JavaBackendError
from app.main import app
from app.model_gateway import ModelStreamEvent, ModelTurn
from app.session_store import session_store

EVALS_DIR = Path(__file__).resolve().parent
DEFAULT_CASES = EVALS_DIR / "cases.jsonl"
EVAL_USER_ID = 9090

DEFAULT_CONFIG: dict[str, Any] = {
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

DEFAULT_METRICS: dict[str, Any] = {
    "averagePositionError": 3.12,
    "trackingRate": 0.98,
    "resourceUtilization": 0.9,
    "averageWaitingTime": 0.4,
    "schedulingSwitches": 7,
    "totalSteps": 12,
}


@dataclass
class Outcome:
    """Everything one case produced. The grader reads only this."""

    case_id: str
    session: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    java_runs: list[dict[str, Any]] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    http_status: int | None = None
    error: str | None = None

    def event_types(self) -> list[str]:
        return [event["event_type"] for event in self.events]

    def tool_names(self) -> list[str]:
        return [message["tool_name"] for message in self.messages if message["role"] == "tool"]

    def tool_message(self, tool_name: str) -> dict[str, Any] | None:
        hits = [
            message
            for message in self.messages
            if message["role"] == "tool" and message["tool_name"] == tool_name
        ]
        return hits[-1] if hits else None

    def last_assistant(self) -> dict[str, Any] | None:
        hits = [message for message in self.messages if message["role"] == "assistant" and message["content"]]
        return hits[-1] if hits else None


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    """Read the JSONL case file. Blank lines and ``//`` lines are ignored so it stays editable."""
    source = Path(path or DEFAULT_CASES)
    cases: list[dict[str, Any]] = []
    for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        try:
            case = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{source.name}:{number} is not valid JSON: {exc.msg}") from exc
        if "id" not in case:
            raise ValueError(f"{source.name}:{number} has no id")
        cases.append(case)
    return cases


class ScriptedModel:
    """
    The stand-in model for one case.

    It answers by *which* subsystem is calling, deduced from the system prompt, so a case reads as
    "the model decided X, said Y, proposed Z" without depending on call order.
    """

    def __init__(self, case: dict[str, Any]):
        self.case = case
        model = case.get("model") or {}
        self.answer: str = model.get("answer") or ""
        self.steps: list[dict[str, Any]] = list(model.get("steps") or [])
        self.plan: dict[str, Any] | None = model.get("plan")
        self.reflection: dict[str, Any] | None = model.get("reflection")
        self.analysis: dict[str, Any] | None = model.get("analysis")
        self.memory_note: str = model.get("memory_note") or ""
        self.calls: list[dict[str, Any]] = []
        self._loop_step = 0

    # ------------------------------------------------------------------ the loop / concept answer

    async def stream(self, system_prompt: str, messages, tools, credential):
        kind = "concept" if "不需要你运行仿真" in system_prompt else "loop"
        self.calls.append({"kind": kind, "tool_names": [tool["name"] for tool in tools]})

        if kind == "concept":
            # Streamed in pieces, so the suite also covers the token path rather than only the
            # final text.
            for index in range(0, len(self.answer), 7):
                yield ModelStreamEvent("text", text=self.answer[index : index + 7])
            return

        step = self.steps[self._loop_step] if self._loop_step < len(self.steps) else None
        self._loop_step += 1
        if step is None:
            yield ModelStreamEvent("text", text="Nothing further.")
            return
        if step.get("text"):
            yield ModelStreamEvent("text", text=step["text"])
        for call in step.get("tool_calls") or []:
            yield ModelStreamEvent(
                "tool_calls",
                tool_calls=[
                    _call_record(f"eval_{self._loop_step}_{index}", call)
                    for index, call in enumerate(step["tool_calls"])
                ],
            )

    # ------------------------------------------------------------------ planner / reflector / memory

    async def complete(self, messages, credential, json_mode: bool = True) -> str:
        system_text = " ".join(m.get("content", "") for m in messages if m.get("role") == "system")
        if "实验规划器" in system_text:
            self.calls.append({"kind": "planner"})
            if self.plan is None:
                raise AssertionError("this case has no plan script but the planner was invoked")
            return json.dumps(self.plan, ensure_ascii=False)
        if "自检模块" in system_text:
            self.calls.append({"kind": "reflect"})
            payload = self.reflection or {"supported": True, "problem": "", "correction": ""}
            return json.dumps(payload, ensure_ascii=False)
        if "analysis module" in system_text:
            # The analyst role. Note it arrives through `complete`, which carries no tool channel:
            # the case cannot script a tool call here even if it wanted to, which is the point of
            # the role rather than a limitation of the harness.
            self.calls.append({"kind": "analysis"})
            if self.analysis is None:
                # A reading with the shape the analyst is asked for, but no claims. Cases that care
                # about the reading declare their own.
                return json.dumps(
                    {"summary": "The run completed.", "evidence": [], "limitations": []},
                    ensure_ascii=False,
                )
            return json.dumps(self.analysis, ensure_ascii=False)
        if "long-term memory module" in system_text:
            self.calls.append({"kind": "memory"})
            return self.memory_note
        self.calls.append({"kind": "other"})
        return self.memory_note


def _call_record(call_id: str, raw: dict[str, Any]) -> Any:
    from app.conversation import ToolCallRecord

    return ToolCallRecord(call_id=call_id, name=raw["tool"], arguments=raw.get("arguments") or {})


def _java_stubs(case: dict[str, Any], runs: list[dict[str, Any]], validation_errors: list[str]):
    """Replace only the outbound Java calls. Everything else stays the real code."""
    script = case.get("java") or {}
    metrics = script.get("metrics") or DEFAULT_METRICS
    validate_error = script.get("validate_error")
    run_error = script.get("run_error")
    compare = bool(script.get("compare"))

    async def fake_validate(config):
        if validate_error:
            validation_errors.append(validate_error)
            raise JavaBackendError("JAVA_REQUEST_FAILED", validate_error, 400)
        return {"valid": True}

    async def fake_run(config, authorization=None):
        if run_error:
            raise JavaBackendError("JAVA_REQUEST_FAILED", run_error, 500)
        runs.append({"config": dict(config)})
        return {
            "runId": f"run-{len(runs)}",
            "config": dict(config),
            "metrics": dict(metrics),
            "steps": [{"timeStep": index} for index in range(int(config.get("simulationSteps") or 3))],
        }

    async def fake_compare(config, authorization=None):
        runs.append({"config": dict(config), "compare": True})
        return {
            "roundRobin": {"metrics": dict(metrics)},
            "priority": {"metrics": {**metrics, "averagePositionError": 2.5}},
            "priorityMinusRoundRobin": {"averagePositionError": -0.62},
        }

    return fake_validate, fake_run, fake_compare


def run_case(case: dict[str, Any]) -> Outcome:
    """
    Drive one case through the real HTTP surface and return what happened.

    Deliberately total: a case that explodes produces an Outcome carrying the error rather than an
    exception, because one broken case must not abort the report for the other twenty.
    """
    outcome = Outcome(case_id=case["id"])
    scripted = ScriptedModel(case)
    stubbed_validate, stubbed_run, stubbed_compare = _java_stubs(
        case, outcome.java_runs, outcome.validation_errors
    )
    setup = case.get("setup") or {}
    working_config = {**DEFAULT_CONFIG, **(setup.get("working_config") or {})}
    auto_approve = bool(setup.get("auto_approve", False))

    stored: dict[str, Any] = {}

    async def fake_default_config():
        return dict(working_config)

    async def fake_save(snapshot, authorization):
        stored[snapshot["session_id"]] = json.loads(json.dumps(snapshot))

    async def fake_find(session_id, authorization):
        return stored.get(session_id)

    async def fake_list(authorization, limit=30):
        return []

    async def fake_delete(session_id, authorization):
        stored.pop(session_id, None)

    async def fake_get_memory(authorization):
        return setup.get("memory") or ""

    async def fake_save_memory(memory, authorization):
        return None

    async def fake_classify_intent(session, credential):
        model = case.get("model") or {}
        route = model.get("route")
        if not route:
            raise AssertionError("this case has no scripted route")
        because = model.get("because") or f"the case scripted the {route} route"
        return SupervisorDecision(route, model.get("clarify_question"), because)

    session_store.drop_for_user(EVAL_USER_ID)

    def _forbid_outbound(*_args, **_kwargs):
        raise AssertionError(
            "a scripted case tried to make a real outbound HTTP call, so the harness is not "
            "patching every provider or Java entry point it should. Determinism here is a claim "
            "about the suite, and this is what enforces it."
        )

    overrides = {
        "app.main.get_default_config": fake_default_config,
        "app.main.save_agent_conversation": fake_save,
        "app.main.find_agent_conversation": fake_find,
        "app.main.list_agent_conversations": fake_list,
        "app.main.delete_agent_conversation": fake_delete,
        "app.main.get_agent_memory": fake_get_memory,
        "app.main.save_agent_memory": fake_save_memory,
        "app.domain_tools.validate_experiment": stubbed_validate,
        "app.domain_tools.run_simulation": stubbed_run,
        "app.domain_tools.compare_scheduling_policies": stubbed_compare,
        "app.agent_graph.classify_intent": fake_classify_intent,
        # Every module that calls a provider holds its own reference to `complete`, so each one has
        # to be replaced. Patching only the graph would leave the reflection auditor, the memory
        # distiller and the result analyst talking to the real internet — which is what happened
        # before this list was completed, and it was invisible because all three swallow gateway
        # failures. It cost a network round trip per case and made the suite depend on a third
        # party being unreachable-but-fast.
        "app.agent_graph.complete": scripted.complete,
        "app.reflection.complete": scripted.complete,
        "app.memory.complete": scripted.complete,
        "app.result_analysis.complete": scripted.complete,
        "app.model_planner.complete": scripted.complete,
        "app.agent_graph.stream_call_with_tools": scripted.stream,
        "app.agent_loop.stream_call_with_tools": scripted.stream,
        # Blanket guard rather than a per-module list. The inbound request goes through httpx.Client
        # (the ASGI transport), so AsyncClient is exactly the outbound channel: this fails loudly if
        # any future provider or Java path slips through the patches above.
        "httpx.AsyncClient.send": _forbid_outbound,
    }
    app.dependency_overrides[require_agent_user] = lambda: {
        "authorization": "Bearer eval-token",
        "user": {"userId": EVAL_USER_ID},
        "user_id": EVAL_USER_ID,
    }

    try:
        with ExitStack() as stack:
            for target, replacement in overrides.items():
                stack.enter_context(patch(target, replacement))
            client = TestClient(app)
            session_id = _drive(client, case, auto_approve, outcome)
        # The persisted snapshot is what the UI would reload, so grading reads that rather than the
        # live object: a field that is not serialised is not really part of the product's state.
        _record(outcome, stored.get(session_id), session_store.get(session_id), scripted.calls)
    except Exception as exc:  # noqa: BLE001 - a broken case is data, not a crash
        outcome.error = f"{type(exc).__name__}: {exc}"
    finally:
        app.dependency_overrides.pop(require_agent_user, None)
        session_store.drop_for_user(EVAL_USER_ID)
    return outcome


def _drive(client: TestClient, case: dict[str, Any], auto_approve: bool, outcome: Outcome) -> str | None:
    """Create a conversation, send the message, answer the confirmation, return the session id."""
    created = client.post(
        "/api/v1/agent/conversations",
        json={"auto_approve": auto_approve, "model_provider": "openai", "model_name": "eval-model"},
    )
    outcome.http_status = created.status_code
    if created.status_code != 200:
        raise AssertionError(f"conversation creation failed: {created.status_code} {created.text[:200]}")
    session_id = created.json()["session_id"]

    payload = {
        "message": case["message"],
        "model_provider": "openai",
        "model_name": "eval-model",
        "auto_approve": auto_approve,
    }
    headers = {"X-Model-Api-Key": "eval-key"}

    if case.get("stream"):
        # The streaming endpoint is the one the UI uses, so a case may opt into it. The frames are
        # parsed rather than asserted here; grading reads the final session either way.
        body = _post_stream(client, f"/api/v1/agent/conversations/{session_id}/messages/stream", payload, headers)
    else:
        response = client.post(f"/api/v1/agent/conversations/{session_id}/messages", json=payload, headers=headers)
        outcome.http_status = response.status_code
        if response.status_code != 200:
            raise AssertionError(f"message failed: {response.status_code} {response.text[:200]}")
        body = response.json()

    decision = case.get("decision")
    if decision and body.get("pending"):
        approve = decision == "approve"
        response = client.post(
            f"/api/v1/agent/conversations/{session_id}/decision",
            json={"approve": approve, "model_provider": "openai", "model_name": "eval-model"},
            headers=headers,
        )
        if response.status_code != 200:
            raise AssertionError(f"decision failed: {response.status_code} {response.text[:200]}")
    return session_id


def _post_stream(client: TestClient, path: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    """Drive the SSE endpoint and return the authoritative session frame."""
    frames: list[tuple[str, Any]] = []
    with client.stream("POST", path, json=payload, headers=headers) as response:
        if response.status_code != 200:
            raise AssertionError(f"stream failed: {response.status_code}")
        event = "message"
        for line in response.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                raw = line[5:].strip()
                try:
                    frames.append((event, json.loads(raw)))
                except json.JSONDecodeError:
                    continue
    session_frames = [data for name, data in frames if name == "session"]
    if not session_frames:
        raise AssertionError("the stream closed without a session frame")
    return session_frames[-1]


def _record(
    outcome: Outcome,
    snapshot: dict[str, Any] | None,
    session,
    model_calls: list[dict[str, Any]],
) -> None:
    """Snapshot the outcome into plain JSON so grading never touches live objects."""
    if not snapshot and session is not None:
        snapshot = json.loads(session.model_dump_json())
    outcome.session = snapshot or {}
    outcome.messages = list(outcome.session.get("messages") or [])
    outcome.events = list(outcome.session.get("events") or [])
    # Recorded separately from the session: how many times each role's model call happened is
    # coordination evidence, and it never appears in the transcript.
    outcome.model_calls = list(model_calls)
