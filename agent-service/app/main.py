import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from .agent_graph import analyze_turn, reflect_turn, run_turn
from .agent_loop import cancel_pending, resolve_decision
from .agent_service import (
    AgentWorkflowError,
    confirm_session,
    create_session,
    execute_session_tool,
)
from .auth import require_agent_user
from .config import MODEL_API_KEY, MODEL_PROVIDER
from .conversation import AgentMessage, now_iso
from .domain_tools import CONFIRMATION_REQUIRED
from .knowledge import corpus_directory, get_index, retrieve
from .java_client import (
    JavaBackendError,
    delete_agent_conversation,
    find_agent_conversation,
    get_agent_memory,
    get_agent_trace,
    get_default_config,
    list_agent_conversations,
    run_simulation,
    save_agent_conversation,
    save_agent_memory,
    save_agent_trace,
    update_agent_trace,
)
from .model_gateway import (
    ModelCredential,
    ModelGatewayError,
    current_provider,
    probe,
    provider_catalog,
    resolve_credential,
)
from .model_planner import build_plan_with_model
from . import memory
from .models import (
    AgentSession,
    AgentSessionSummary,
    AgentTrace,
    ConfirmResponse,
    ExecuteToolRequest,
    ExperimentPlan,
    ModelConnectionTest,
    ModelProbeRequest,
    NewSessionRequest,
    PlanRequest,
    SendMessageRequest,
    ToolCallResult,
    ToolDecisionRequest,
    ToolRunRequest,
)
from .session_store import session_store, set_title_from, summarize
from .tools import list_tool_definitions
from .trace import trace_store


app = FastAPI(
    title="FusionPilot Agent Service",
    version="0.4.0",
)

# Only the web frontend may call this service from a browser. The model token rides the
# X-Model-Api-Key header, so a loose CORS policy would let a hostile page ask the user's own
# browser to relay requests here. Everything else is still gated by the bearer token, but the
# origin allow-list is a cheap first line of defence.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def optional_model_credential(
    x_model_api_key: str | None = Header(default=None, alias="X-Model-Api-Key"),
    x_model_api_base: str | None = Header(default=None, alias="X-Model-Api-Base"),
) -> dict:
    """
    The user's own model token, if they supplied one.

    It arrives as a header and is carried on this dict only. It is never placed on a pydantic
    model, never written to a trace event, and never persisted with the agent session, so a
    bearer token cannot leak into the database or a later API response.
    """
    return {"api_key": x_model_api_key, "api_base_url": x_model_api_base}


def resolve_for_request(
    provider: str | None,
    model: str | None,
    supplied: dict,
    fallback_base_url: str | None = None,
) -> ModelCredential | None:
    """
    Build the credential for this request, or None when the caller wants local rule mode.

    A missing key is not an HTTP error here: the planner reports the fallback itself so the user
    sees that a model was requested but no token was available. An unsupported provider name is a
    caller mistake and is rejected.
    """
    provider_name = (provider or MODEL_PROVIDER or "rule").strip().lower()
    if provider_name == "rule":
        return None
    try:
        return resolve_credential(
            provider,
            model,
            supplied.get("api_key"),
            fallback_base_url or supplied.get("api_base_url"),
        )
    except ModelGatewayError as exc:
        if exc.code == "MODEL_PROVIDER_UNSUPPORTED":
            raise _model_error(exc) from exc
        return None


@app.get("/api/v1/agent/health")
async def health() -> dict:
    return {
        "service": "fusionpilot-agent",
        "status": "UP",
        "workflow": "multi-turn-tool-loop",
        "serverModelProvider": MODEL_PROVIDER,
        "serverModelConfigured": bool(MODEL_API_KEY),
        "acceptsUserApiKey": True,
        "confirmationRequiredTools": sorted(CONFIRMATION_REQUIRED),
    }


@app.post("/api/v1/agent/plan", response_model=ExperimentPlan)
async def create_plan(
    request: PlanRequest,
    _auth: dict = Depends(require_agent_user),
    supplied: dict = Depends(optional_model_credential),
) -> ExperimentPlan:
    credential = resolve_for_request(
        request.model_provider,
        request.model_name,
        supplied,
        request.model_api_base_url,
    )
    try:
        default_config = await get_default_config()
    except JavaBackendError as exc:
        raise _java_error(exc) from exc
    try:
        return await build_plan_with_model(request, default_config, credential)
    except ModelGatewayError as exc:
        raise _model_error(exc) from exc


@app.get("/api/v1/agent/models")
async def models(
    _auth: dict = Depends(require_agent_user),
    supplied: dict = Depends(optional_model_credential),
    provider: str | None = Query(default=None, max_length=40),
    model: str | None = Query(default=None, max_length=120),
) -> dict:
    api_key = supplied.get("api_key")
    return {
        "current": current_provider(provider, model, api_key),
        "providers": provider_catalog(api_key),
        # Lets the UI distinguish "I brought a token" from "the server has one configured".
        "hasRequestKey": bool((api_key or "").strip()),
    }


@app.post("/api/v1/agent/models/test", response_model=ModelConnectionTest)
async def test_model(
    request: ModelProbeRequest,
    _auth: dict = Depends(require_agent_user),
    supplied: dict = Depends(optional_model_credential),
) -> ModelConnectionTest:
    try:
        credential = resolve_credential(
            request.provider,
            request.model,
            supplied.get("api_key"),
            request.api_base_url or supplied.get("api_base_url"),
        )
    except ModelGatewayError as exc:
        raise _model_error(exc) from exc
    try:
        result = await probe(credential)
    except ModelGatewayError as exc:
        raise _model_error(exc) from exc
    return ModelConnectionTest(
        provider=result["provider"],
        label=result["label"],
        model=result["model"],
        reply=result["reply"],
    )


@app.get("/api/v1/agent/tools")
async def tools(_auth: dict = Depends(require_agent_user)) -> dict:
    return {"tools": [tool.model_dump() for tool in list_tool_definitions()]}


@app.get("/api/v1/agent/tools/default-config")
async def default_config(_auth: dict = Depends(require_agent_user)) -> dict:
    try:
        return await get_default_config()
    except JavaBackendError as exc:
        raise _java_error(exc) from exc


@app.post("/api/v1/agent/tools/run-simulation")
async def execute_simulation(
    request: ToolRunRequest,
    auth: dict = Depends(require_agent_user),
) -> dict:
    if not request.confirmed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONFIRMATION_REQUIRED",
                "message": "User confirmation is required before running a simulation.",
            },
        )
    try:
        return await run_simulation(request.config, auth["authorization"])
    except JavaBackendError as exc:
        raise _java_error(exc) from exc


@app.post("/api/v1/agent/sessions", response_model=AgentTrace)
async def create_agent_session(
    request: PlanRequest,
    auth: dict = Depends(require_agent_user),
    supplied: dict = Depends(optional_model_credential),
) -> AgentTrace:
    credential = resolve_for_request(
        request.model_provider,
        request.model_name,
        supplied,
        request.model_api_base_url,
    )
    try:
        trace = await create_session(request, auth["user_id"], credential)
        await save_agent_trace(trace.model_dump(mode="json"), auth["authorization"])
        return trace
    except JavaBackendError as exc:
        raise _java_error(exc) from exc


@app.post("/api/v1/agent/sessions/{trace_id}/confirm", response_model=ConfirmResponse)
async def confirm_agent_session(
    trace_id: str,
    auth: dict = Depends(require_agent_user),
) -> ConfirmResponse:
    try:
        await _hydrate_trace(trace_id, auth)
        response = confirm_session(trace_id, auth["user_id"])
        trace = trace_store.get(trace_id)
        if trace is not None:
            await update_agent_trace(trace.model_dump(mode="json"), auth["authorization"])
        return response
    except AgentWorkflowError as exc:
        raise _workflow_error(exc) from exc


@app.post("/api/v1/agent/sessions/{trace_id}/execute", response_model=ToolCallResult)
async def execute_agent_tool(
    trace_id: str,
    request: ExecuteToolRequest,
    auth: dict = Depends(require_agent_user),
    supplied: dict = Depends(optional_model_credential),
) -> ToolCallResult:
    credential = resolve_for_request(
        request.model_provider,
        request.model_name,
        supplied,
        request.model_api_base_url,
    )
    try:
        await _hydrate_trace(trace_id, auth)
        response = await execute_session_tool(
            trace_id,
            request,
            auth["authorization"],
            auth["user_id"],
            credential,
        )
        trace = trace_store.get(trace_id)
        if trace is not None:
            await update_agent_trace(trace.model_dump(mode="json"), auth["authorization"])
        return response
    except JavaBackendError as exc:
        raise _java_error(exc) from exc
    except AgentWorkflowError as exc:
        raise _workflow_error(exc) from exc


@app.get("/api/v1/agent/sessions/{trace_id}", response_model=AgentTrace)
async def get_agent_session(
    trace_id: str,
    auth: dict = Depends(require_agent_user),
) -> AgentTrace:
    local_trace = trace_store.get(trace_id)
    if local_trace is not None:
        if local_trace.owner_user_id != auth["user_id"]:
            raise HTTPException(
                status_code=404,
                detail={"code": "TRACE_NOT_FOUND", "message": "Agent trace not found."},
            )
        return local_trace
    persisted = await get_agent_trace(trace_id, auth["authorization"])
    if persisted is not None:
        trace = AgentTrace.model_validate(persisted)
        trace_store.restore(trace)
        return trace
    raise HTTPException(
        status_code=404,
        detail={"code": "TRACE_NOT_FOUND", "message": "Agent trace not found."},
    )


async def _hydrate_trace(trace_id: str, auth: dict) -> AgentTrace:
    trace = trace_store.get(trace_id)
    if trace is not None and trace.owner_user_id == auth["user_id"]:
        return trace
    persisted = await get_agent_trace(trace_id, auth["authorization"])
    if persisted is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "TRACE_NOT_FOUND", "message": "Agent trace not found."},
        )
    trace = AgentTrace.model_validate(persisted)
    trace_store.restore(trace)
    return trace


# --------------------------------------------------------------- multi-turn conversations


def _session_not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "SESSION_NOT_FOUND", "message": "Agent conversation not found."},
    )


async def _hydrate_session(session_id: str, auth: dict) -> AgentSession:
    """
    Load a conversation, preferring the live copy.

    Ownership is enforced on both paths: a persisted snapshot carries its owner, so knowing a
    session id is not enough to read someone else's conversation.
    """
    session = session_store.get(session_id)
    if session is not None:
        if session.owner_user_id != auth["user_id"]:
            raise _session_not_found()
        return session
    persisted = await find_agent_conversation(session_id, auth["authorization"])
    if persisted is None:
        raise _session_not_found()
    try:
        session = AgentSession.model_validate(persisted)
    except ValidationError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "SESSION_CORRUPT", "message": f"Stored conversation could not be read: {exc.error_count()} field error(s)."},
        ) from exc
    if session.owner_user_id != auth["user_id"]:
        raise _session_not_found()
    session_store.restore(session)
    return session


async def _persist_session(session: AgentSession, auth: dict) -> None:
    try:
        snapshot = session.model_dump(mode="json")
        # Stored beside the snapshot so the conversation list can show a configuration digest
        # without parsing every transcript.
        snapshot["working_summary"] = summarize(session).working_summary
        await save_agent_conversation(snapshot, auth["authorization"])
    except JavaBackendError as exc:
        raise _java_error(exc) from exc


# --------------------------------------------------------------------------- turn preparation


def _start_turn(session: AgentSession, request: SendMessageRequest, credential: ModelCredential | None) -> None:
    """Shared preamble for a user turn, identical on the JSON and the streaming path."""
    if request.auto_approve is not None:
        session.auto_approve = request.auto_approve
    if credential is not None:
        session.provider = credential.provider
        session.model = credential.model
    cancel_pending(
        session,
        "The user sent a new message before answering this request, so it was not run.",
    )
    session.messages.append(AgentMessage(role="user", content=request.message))
    set_title_from(session, request.message)
    if session.status != "ACTIVE":
        session.status = "ACTIVE"


async def _distill_memory(
    session: AgentSession,
    credential: ModelCredential | None,
    auth: dict,
) -> None:
    """
    Update the user's long-term note after a settled turn.

    Best-effort: a missing model or a failed distillation never blocks the reply. Only a finished
    turn (no pending confirmation) is distilled, so a paused approval is not mistaken for a result.
    """
    if credential is None:
        return
    if session.pending is not None or session.status != "ACTIVE":
        return
    try:
        updated = await memory.distill(session.memory, session, credential)
        if updated:
            session.memory = updated
            await save_agent_memory(updated, auth["authorization"])
    except (ModelGatewayError, JavaBackendError):
        pass


# --------------------------------------------------------------------------- streaming (SSE)

STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# Turns that outlive their request (the client closed the stream mid-turn) are kept here so the
# event loop holds a strong reference until they finish and persist.
_BACKGROUND_TURNS: set[asyncio.Task] = set()


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_run(session: AgentSession, runner) -> AsyncIterator[str]:
    """
    Yield SSE frames while a turn runs.

    ``runner`` is an async callable taking one ``on_event`` sink; it performs the work and, in its
    ``finally``, persists the session. The pump forwards every event and flushes new transcript
    messages alongside, then ends with the authoritative session. A client that drops mid-stream
    does not lose the turn: the work runs as a task that finishes and persists on its own.
    """
    queue: asyncio.Queue = asyncio.Queue()

    def on_event(event_type: str, payload: dict[str, Any]) -> None:
        queue.put_nowait((event_type, payload))

    task = asyncio.ensure_future(runner(on_event))
    _BACKGROUND_TURNS.add(task)
    task.add_done_callback(_BACKGROUND_TURNS.discard)

    sent_messages = 0
    try:
        while True:
            if task.done() and queue.empty():
                break
            getter = asyncio.ensure_future(queue.get())
            done, _ = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)

            # New transcript messages are sent before any event, so the UI never shows a tool card
            # whose message it has not yet received.
            while sent_messages < len(session.messages):
                yield _sse("message", session.messages[sent_messages].model_dump(mode="json"))
                sent_messages += 1

            if getter in done:
                event_type, payload = getter.result()
                yield _sse("progress", {"event_type": event_type, "payload": payload, "created_at": now_iso()})
                continue

            getter.cancel()
            # The turn finished: flush everything left in the queue, then the final state.
            while not queue.empty():
                event_type, payload = queue.get_nowait()
                yield _sse("progress", {"event_type": event_type, "payload": payload, "created_at": now_iso()})
            while sent_messages < len(session.messages):
                yield _sse("message", session.messages[sent_messages].model_dump(mode="json"))
                sent_messages += 1
            break
    except Exception as exc:
        yield _sse("error", {"code": _error_code(exc), "message": _error_message(exc)})
        return

    # `Task.exception()` returns the exception (or None) rather than raising it, so the failure has
    # to be checked explicitly instead of with try/except.
    failure = task.exception()
    if failure is not None:
        yield _sse("error", {"code": _error_code(failure), "message": _error_message(failure)})
        yield _sse("session", session.model_dump(mode="json"))
        return

    yield _sse("session", session.model_dump(mode="json"))


async def _stream_turn(
    session: AgentSession,
    credential: ModelCredential | None,
    auth: dict,
) -> AsyncIterator[str]:
    async def runner(on_event) -> None:
        try:
            await run_turn(session, credential, auth["authorization"], on_event=on_event)
        finally:
            await _distill_memory(session, credential, auth)
            await _persist_session(session, auth)

    async for frame in _stream_run(session, runner):
        yield frame


def _error_code(exc: Exception) -> str:
    if isinstance(exc, ModelGatewayError):
        return exc.code
    if isinstance(exc, HTTPException):
        return str(getattr(exc, "detail", {}).get("code", "HTTP_ERROR"))
    return type(exc).__name__


def _error_message(exc: Exception) -> str:
    if isinstance(exc, ModelGatewayError):
        return exc.message
    if isinstance(exc, HTTPException):
        detail = getattr(exc, "detail", "")
        return str(detail.get("message", detail)) if isinstance(detail, dict) else str(detail)
    return str(exc)


@app.get("/api/v1/agent/knowledge/search")
async def search_knowledge(
    auth: dict = Depends(require_agent_user),
    q: str = Query(min_length=1, max_length=400),
    limit: int = Query(default=3, ge=1, le=10),
) -> dict:
    """
    Search the platform's own reference material.

    Exposed separately from the chat so retrieval can be inspected directly. A wrong answer and a
    bad index look identical in a transcript; this is what tells the two apart, and it is also how
    an evaluation harness checks retrieval without spending a model call.
    """
    hits = retrieve(q, limit=limit)
    return {
        "query": q,
        "corpus": {
            "directory": str(corpus_directory()),
            "chunk_count": len(get_index()),
        },
        "matches": [{**hit.as_citation(), "excerpt": hit.chunk.text} for hit in hits],
    }


@app.post("/api/v1/agent/conversations", response_model=AgentSession)
async def create_conversation(
    request: NewSessionRequest,
    auth: dict = Depends(require_agent_user),
) -> AgentSession:
    try:
        default_config = await get_default_config()
        memory = await get_agent_memory(auth["authorization"])
    except JavaBackendError as exc:
        raise _java_error(exc) from exc
    session = session_store.create(
        owner_user_id=auth["user_id"],
        default_config=default_config,
        auto_approve=request.auto_approve,
        provider=(request.model_provider or MODEL_PROVIDER or "rule").strip().lower(),
        model=request.model_name,
        memory=memory,
    )
    await _persist_session(session, auth)
    return session


@app.get("/api/v1/agent/conversations", response_model=list[AgentSessionSummary])
async def list_conversations(
    auth: dict = Depends(require_agent_user),
    limit: int = Query(default=30, ge=1, le=100),
) -> list[AgentSessionSummary]:
    local = session_store.list_for_user(auth["user_id"])
    try:
        stored = await list_agent_conversations(auth["authorization"], limit)
    except JavaBackendError:
        # Live conversations are still usable; only the older stored ones are missing.
        return local[:limit]

    seen = {item.session_id for item in local}
    merged = list(local)
    for raw in stored:
        try:
            item = AgentSessionSummary.model_validate(raw)
        except ValidationError:
            continue
        if item.session_id not in seen:
            merged.append(item)
    merged.sort(key=lambda item: item.updated_at, reverse=True)
    return merged[:limit]


@app.get("/api/v1/agent/conversations/{session_id}", response_model=AgentSession)
async def get_conversation(
    session_id: str,
    auth: dict = Depends(require_agent_user),
) -> AgentSession:
    return await _hydrate_session(session_id, auth)


@app.delete("/api/v1/agent/conversations/{session_id}")
async def delete_conversation(
    session_id: str,
    auth: dict = Depends(require_agent_user),
) -> dict:
    await _hydrate_session(session_id, auth)
    try:
        await delete_agent_conversation(session_id, auth["authorization"])
    except JavaBackendError as exc:
        raise _java_error(exc) from exc
    session_store.drop(session_id)
    return {"deleted": session_id}


@app.post("/api/v1/agent/conversations/{session_id}/messages", response_model=AgentSession)
async def send_conversation_message(
    session_id: str,
    request: SendMessageRequest,
    auth: dict = Depends(require_agent_user),
    supplied: dict = Depends(optional_model_credential),
) -> AgentSession:
    """
    Append a user turn and run the loop until it stops or needs approval.

    An unanswered confirmation is closed out first. Leaving it open would put a second question
    in front of the user while the transcript still owed a result for the first tool call.
    """
    session = await _hydrate_session(session_id, auth)
    credential = resolve_for_request(
        request.model_provider,
        request.model_name,
        supplied,
        request.model_api_base_url,
    )
    _start_turn(session, request, credential)

    try:
        await run_turn(session, credential, auth["authorization"])
    except ModelGatewayError as exc:
        # The transcript is kept so the user can see what they asked and retry.
        await _persist_session(session, auth)
        raise _model_error(exc) from exc
    await _distill_memory(session, credential, auth)
    await _persist_session(session, auth)
    return session


@app.post("/api/v1/agent/conversations/{session_id}/decision", response_model=AgentSession)
async def decide_conversation_tool(
    session_id: str,
    request: ToolDecisionRequest,
    auth: dict = Depends(require_agent_user),
    supplied: dict = Depends(optional_model_credential),
) -> AgentSession:
    session = await _hydrate_session(session_id, auth)
    credential = resolve_for_request(
        request.model_provider,
        request.model_name,
        supplied,
        request.model_api_base_url,
    )
    try:
        calls_before = session.tool_call_count
        await resolve_decision(session, request.approve, credential, auth["authorization"])
        # The approval turn continues in the loop, not through the graph, so the analyst and the
        # critic have to be invoked here too — otherwise the one turn that reads a result the user
        # just approved is the one turn nothing interprets or audits.
        await analyze_turn(session, credential, session.tool_call_count > calls_before)
        await reflect_turn(session, credential)
    except ModelGatewayError as exc:
        await _persist_session(session, auth)
        raise _model_error(exc) from exc
    await _distill_memory(session, credential, auth)
    await _persist_session(session, auth)
    return session


@app.post("/api/v1/agent/conversations/{session_id}/messages/stream")
async def stream_conversation_message(
    session_id: str,
    request: SendMessageRequest,
    auth: dict = Depends(require_agent_user),
    supplied: dict = Depends(optional_model_credential),
) -> StreamingResponse:
    """
    The same turn as `POST .../messages`, delivered as server-sent events.

    Each step is sent the moment it happens, then the authoritative session closes the stream. The
    client renders from the `message` frames and replaces its state with the final `session`.
    """
    session = await _hydrate_session(session_id, auth)
    credential = resolve_for_request(
        request.model_provider,
        request.model_name,
        supplied,
        request.model_api_base_url,
    )
    _start_turn(session, request, credential)
    return StreamingResponse(
        _stream_turn(session, credential, auth),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


@app.post("/api/v1/agent/conversations/{session_id}/decision/stream")
async def stream_conversation_decision(
    session_id: str,
    request: ToolDecisionRequest,
    auth: dict = Depends(require_agent_user),
    supplied: dict = Depends(optional_model_credential),
) -> StreamingResponse:
    session = await _hydrate_session(session_id, auth)
    credential = resolve_for_request(
        request.model_provider,
        request.model_name,
        supplied,
        request.model_api_base_url,
    )

    async def runner(on_event) -> None:
        try:
            calls_before = session.tool_call_count
            await resolve_decision(
                session,
                request.approve,
                credential,
                auth["authorization"],
                on_event=on_event,
            )
            # Same reason as the JSON endpoint above: this turn is outside the graph, so the
            # analyst and the critic are invoked explicitly and their events stream like any other.
            await analyze_turn(session, credential, session.tool_call_count > calls_before, on_event)
            await reflect_turn(session, credential, on_event=on_event)
        finally:
            await _distill_memory(session, credential, auth)
            await _persist_session(session, auth)

    return StreamingResponse(
        _stream_run(session, runner),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


def _java_error(exc: JavaBackendError) -> HTTPException:
    """
    Relay a Java failure.

    A 4xx from the Java core means the request itself was rejected, so it is reported as a bad
    request rather than as the backward dependency being down.
    """
    if exc.status_code == 401:
        status_code = 401
    elif 400 <= exc.status_code < 500:
        status_code = 400
    else:
        status_code = 503
    return HTTPException(
        status_code=status_code,
        detail={
            "code": exc.code,
            "message": exc.message,
            "dependency": "java-backend",
        },
    )


def _model_error(exc: ModelGatewayError) -> HTTPException:
    """
    Map a gateway failure onto an HTTP status.

    A provider rejecting the credential becomes 401 so the UI can say "the token was refused"
    rather than showing a generic upstream error.
    """
    if exc.code in {"MODEL_API_KEY_MISSING", "MODEL_PROVIDER_UNSUPPORTED", "MODEL_DISABLED"}:
        status_code = 400
    elif exc.code == "MODEL_UNAVAILABLE":
        status_code = 503
    elif exc.code == "MODEL_REQUEST_FAILED" and exc.message.startswith(("401", "403")):
        status_code = 401
    else:
        status_code = 502
    return HTTPException(
        status_code=status_code,
        detail={
            "code": exc.code,
            "message": exc.message,
            "dependency": "model-provider",
        },
    )


def _workflow_error(exc: AgentWorkflowError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )
