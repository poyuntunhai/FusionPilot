"""
End-to-end verification of the multi-turn agent over real HTTP.

No real provider is involved. A mock provider that behaves like an agent (read config, patch it,
run, re-read metrics, answer from them) is started locally and reached through `api_base_url`, so
the whole chain is exercised: request header -> credential -> HTTP -> tool calls parsed -> domain
tools -> Java simulation -> tool results -> next model step.

Run with the Java backend on 8080 and the agent service on 8000:

    python tests/verify_multi_turn_end_to_end.py
"""

import json
import os
import random
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mock_model_server import RECEIVED, serve  # noqa: E402


JAVA = "http://127.0.0.1:8080"
AGENT = "http://127.0.0.1:8000"
MOCK_PORT = 8111
MOCK_BASE = f"http://127.0.0.1:{MOCK_PORT}/v1"

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    mark = "PASS" if condition else "FAIL"
    print(f"  [{mark}] {label}" + (f"  -> {detail}" if detail else ""))
    if not condition:
        FAILURES.append(label)
    return condition


def call(base, method, path, body=None, token=None, extra_headers=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    for key, value in (extra_headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, {"raw": raw}


def captcha():
    _, payload = call(JAVA, "GET", "/api/v1/auth/captcha")
    data = payload["data"]
    numbers = [int(value) for value in re.findall(r"-?\d+", data["question"])]
    answer = (
        numbers[0] + numbers[1]
        if "+" in data["question"]
        else numbers[0] - numbers[1]
        if "-" in data["question"]
        else numbers[0] * numbers[1]
    )
    return data["challengeId"], str(answer)


def account(tag: str) -> str:
    username = f"{tag}{random.randint(100000, 999999)}"
    challenge, answer = captcha()
    call(
        JAVA,
        "POST",
        "/api/v1/auth/register",
        {
            "username": username,
            "email": f"{username}@test.local",
            "password": "ProbePass12345",
            "displayName": tag,
            "captchaId": challenge,
            "captchaAnswer": answer,
        },
    )
    challenge, answer = captcha()
    status, payload = call(
        JAVA,
        "POST",
        "/api/v1/auth/login",
        {
            "login": username,
            "password": "ProbePass12345",
            "captchaId": challenge,
            "captchaAnswer": answer,
        },
    )
    assert status == 200, f"login failed: {payload}"
    return payload["data"]["accessToken"]


def send(token, session_id, body, secret="sk-multi-turn-secret"):
    return call(
        AGENT,
        "POST",
        f"/api/v1/agent/conversations/{session_id}/messages",
        body,
        token=token,
        extra_headers={"X-Model-Api-Key": secret},
    )


def decide(token, session_id, approve, provider="openai", secret="sk-multi-turn-secret"):
    return call(
        AGENT,
        "POST",
        f"/api/v1/agent/conversations/{session_id}/decision",
        {"approve": approve, "model_provider": provider, "model_api_base_url": MOCK_BASE},
        token=token,
        extra_headers={"X-Model-Api-Key": secret},
    )


def transcript_is_replayable(messages: list[dict]) -> bool:
    answered = {m.get("tool_call_id") for m in messages if m.get("role") == "tool"}
    for message in messages:
        if message.get("role") == "assistant":
            for tool_call in message.get("tool_calls") or []:
                if tool_call.get("call_id") not in answered:
                    return False
    return True


def rows(payload) -> list:
    """
    Rows from either response shape.

    The agent service returns a bare JSON array while the Java core wraps its payload in an
    envelope, and this script reads from both.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data")
        return data if isinstance(data, list) else []
    return []


def main() -> int:
    global MOCK_BASE
    server = serve()
    MOCK_BASE = f"http://127.0.0.1:{server.server_address[1]}/v1"
    print(f"mock provider on {MOCK_BASE}")
    print(f"agent service health: {json.dumps(call(AGENT, 'GET', '/api/v1/agent/health')[1])}")

    token = account("mturn")
    other = account("mstranger")

    # ---------------------------------------------------------------- 1. agent drives the loop
    print("\n=== 1. multi-turn loop: read -> patch -> run (needs approval) -> read metrics ===")
    status, created = call(AGENT, "POST", "/api/v1/agent/conversations", {"auto_approve": False}, token=token)
    session_id = created["session_id"]
    check("conversation created", status == 200 and bool(session_id), session_id[:8])

    status, paused = send(
        token,
        session_id,
        {
            "message": "Raise the target count a bit and then run the experiment with the Kalman filter.",
            "model_provider": "openai",
            "model_name": "gpt-4o-mini",
            "model_api_base_url": MOCK_BASE,
        },
    )
    check("message accepted", status == 200, str(status))
    check("title taken from the first message", paused["title"].startswith("Raise the target count"), paused["title"][:40])
    check("agent paused for approval", paused["status"] == "AWAITING_CONFIRMATION", paused["status"])
    check(
        "the pending tool is the simulation run",
        paused["pending"]["tool_calls"][0]["name"] == "run_simulation",
        str(paused["pending"]["tool_calls"][0]["name"]),
    )
    done_tools = [m["tool_name"] for m in paused["messages"] if m["role"] == "tool"]
    check(
        "dry tools ran before the gate",
        done_tools == ["get_experiment_config", "update_experiment_config"],
        str(done_tools),
    )
    check(
        "configuration was patched in the session",
        paused["working_config"]["targetCount"] == 5
        and paused["working_config"]["fusionMethod"] == "KALMAN_FILTER",
        json.dumps({k: paused["working_config"][k] for k in ("targetCount", "fusionMethod")}),
    )
    check("no run happened before approval", "run_simulation" not in done_tools)

    print("\n=== 2. approval executes the run and the model reads the Java numbers ===")
    status, finished = decide(token, session_id, True)
    check("decision accepted", status == 200, str(status))
    check("session returned to idle", finished["status"] == "ACTIVE", finished["status"])
    run_message = [m for m in finished["messages"] if m.get("tool_name") == "run_simulation"][-1]
    check("run recorded", run_message["tool_ok"] is True)
    check("run id captured", bool(run_message.get("run_id")), str(run_message.get("run_id"))[:8])
    evidence = {item["metric"]: item["value"] for item in run_message["evidence"]}
    check("evidence present", bool(evidence), str(sorted(evidence)[:3]))
    check(
        "evidence numbers trace to Java",
        all(item["source"] == "java-backend-result" for item in run_message["evidence"]),
    )
    _, stored_run = call(JAVA, "GET", f"/api/v1/simulations/{run_message['run_id']}", token=token)
    java_metrics = stored_run["data"]["metrics"]
    check(
        "evidence matches the stored Java result",
        evidence.get("averagePositionError") == java_metrics["averagePositionError"]
        and evidence.get("trackingRate") == java_metrics["trackingRate"],
        f"agent={evidence.get('averagePositionError')} java={java_metrics['averagePositionError']}",
    )
    final_text = finished["messages"][-1]
    check("model closed the turn with prose", final_text["role"] == "assistant" and bool(final_text["content"]))
    check(
        "the prose quotes the real metrics",
        str(java_metrics["averagePositionError"]) in final_text["content"],
        final_text["content"][:90],
    )
    check("transcript replays cleanly", transcript_is_replayable(finished["messages"]))
    check("message count is tracked", finished["message_count"] if "message_count" in finished else len(finished["messages"]) > 6)

    print("\n=== 3. what the provider actually received ===")
    agent_requests = [item for item in RECEIVED if item["has_tools"]]
    check("provider was reached with a tool catalog", len(agent_requests) >= 4, f"{len(agent_requests)} calls")
    check(
        "the user's token was forwarded as a bearer token",
        all(item["authorization"] == "Bearer sk-multi-turn-secret" for item in agent_requests),
    )
    check(
        "the tool catalog exposes the confirmation-required tools",
        all("run_simulation" in item["tool_names"] for item in agent_requests),
    )
    check("session state was visible to the model", all(item["system_has_state"] for item in agent_requests))

    # ---------------------------------------------------------------- 4. decline path
    print("\n=== 4. declining a run leaves a valid transcript and runs nothing ===")
    _, second = call(AGENT, "POST", "/api/v1/agent/conversations", {}, token=token)
    second_id = second["session_id"]
    _, second_paused = send(
        token,
        second_id,
        {"message": "Run the default experiment.", "model_provider": "openai", "model_api_base_url": MOCK_BASE},
    )
    check("second session also gated", second_paused["status"] == "AWAITING_CONFIRMATION")
    status, declined = decide(token, second_id, False)
    check("decline accepted", status == 200, str(status))
    declined_message = [m for m in declined["messages"] if m.get("tool_name") == "run_simulation"][-1]
    check("the call was closed as declined", declined_message["tool_ok"] is False)
    check("agent acknowledged the refusal", "did not happen" in declined["messages"][-1]["content"], declined["messages"][-1]["content"][:80])
    check("transcript still replays cleanly", transcript_is_replayable(declined["messages"]))
    check("no run id was produced", not declined_message.get("run_id"))

    # ---------------------------------------------------------------- 5. anthropic protocol
    print("\n=== 5. the same loop over the Anthropic message protocol ===")
    _, third = call(AGENT, "POST", "/api/v1/agent/conversations", {"auto_approve": True}, token=token)
    third_id = third["session_id"]
    status, third_body = send(
        token,
        third_id,
        {"message": "Compare the trackers.", "model_provider": "anthropic", "model_name": "claude-3-5-haiku-latest", "model_api_base_url": MOCK_BASE},
    )
    check("anthropic run accepted", status == 200, str(status))
    if status == 200:
        tools_ran = [m["tool_name"] for m in third_body["messages"] if m["role"] == "tool"]
        check("tool calls were parsed out of content blocks", "run_simulation" in tools_ran, str(tools_ran))
        check("auto-approve skipped the gate", third_body["status"] == "ACTIVE", third_body["status"])
        check("transcript replays cleanly", transcript_is_replayable(third_body["messages"]))
        anthropic_calls = [item for item in RECEIVED if item["protocol"] == "anthropic" and item["has_tools"]]
        check("provider saw the anthropic shape", len(anthropic_calls) >= 3, f"{len(anthropic_calls)} calls")
        check(
            "the anthropic key rode the x-api-key header",
            all(item["api_key_header"] == "sk-multi-turn-secret" for item in anthropic_calls),
        )

    # ---------------------------------------------------------------- 6. persistence & isolation
    print("\n=== 6. persistence, listing and ownership ===")
    status, reloaded = call(AGENT, "GET", f"/api/v1/agent/conversations/{session_id}", token=token)
    check("conversation reloads", status == 200 and len(reloaded["messages"]) == len(finished["messages"]))
    status, listed = call(AGENT, "GET", "/api/v1/agent/conversations?limit=10", token=token)
    ids = [item["session_id"] for item in rows(listed)]
    check("conversation appears in the list", session_id in ids, f"{len(ids)} listed")
    if session_id in ids:
        row = next(item for item in rows(listed) if item["session_id"] == session_id)
        check("list carries a configuration digest", bool(row["working_summary"]), row["working_summary"])
        check("list carries message/tool counts", row["message_count"] > 0 and row["tool_call_count"] >= 4,
              f"{row['message_count']} messages, {row['tool_call_count']} tool calls")

    status, foreign = call(AGENT, "GET", f"/api/v1/agent/conversations/{session_id}", token=other)
    check("another user cannot read it", status == 404, str(status))
    status, _ = call(
        AGENT,
        "POST",
        f"/api/v1/agent/conversations/{session_id}/messages",
        {"message": "let me in", "model_provider": "openai"},
        token=other,
        extra_headers={"X-Model-Api-Key": "sk-multi-turn-secret"},
    )
    check("another user cannot write to it", status == 404, str(status))
    status, foreign_list = call(AGENT, "GET", "/api/v1/agent/conversations", token=other)
    check(
        "another user's list is empty",
        all(item["session_id"] != session_id for item in rows(foreign_list)),
    )

    print("\n=== 7. another user's token is not accepted as this user's ===")
    status, other_health = call(AGENT, "GET", "/api/v1/agent/health")
    check("agent health reachable without auth", status == 200)
    check(
        "stored conversations are scoped per user",
        len(rows(call(AGENT, "GET", "/api/v1/agent/conversations", token=token)[1])) > 0
        and len(rows(call(AGENT, "GET", "/api/v1/agent/conversations", token=other)[1])) == 0,
    )

    print("\n=== 8. the token is nowhere in what was returned ===")
    check("token absent from the paused snapshot", "sk-multi-turn-secret" not in json.dumps(paused))
    check("token absent from the finished snapshot", "sk-multi-turn-secret" not in json.dumps(finished))

    print("\n================ SUMMARY ================")
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed:")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
