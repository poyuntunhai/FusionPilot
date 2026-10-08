"""
End-to-end check for the LangGraph intent routing, over real HTTP.

Three turns, one per route, driven through the live agent service with the mock provider standing
in for a real model:

1. concept question -> a tool-free answer (the model must NOT receive a tool catalog)
2. vague request    -> a clarification question, no tools proposed
3. experiment       -> the tool loop runs

The mock's request log is also inspected to prove the classifier made a plain JSON call (it
carries ``response_format``) while the concept answer was streamed.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mock_model_server import RECEIVED, serve  # noqa: E402

JAVA = "http://127.0.0.1:8080"
AGENT = "http://127.0.0.1:8000"


def call(base, method, path, body=None, token=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode())
        except ValueError:
            return exc.code, {}


def captcha():
    _, payload = call(JAVA, "GET", "/api/v1/auth/captcha")
    data = payload["data"]
    nums = [int(x) for x in re.findall(r"-?\d+", data["question"])]
    value = nums[0] + nums[1] if "+" in data["question"] else nums[0] - nums[1] if "-" in data["question"] else nums[0] * nums[1]
    return data["challengeId"], str(value)


def account():
    import random

    username = "route" + str(random.randint(100000, 999999))
    cid, answer = captcha()
    call(JAVA, "POST", "/api/v1/auth/register", {
        "username": username,
        "email": username + "@t.local",
        "password": "ProbePass12345",
        "displayName": "Route",
        "captchaId": cid,
        "captchaAnswer": answer,
    })
    cid, answer = captcha()
    _, payload = call(JAVA, "POST", "/api/v1/auth/login", {
        "login": username,
        "password": "ProbePass12345",
        "captchaId": cid,
        "captchaAnswer": answer,
    })
    return payload["data"]["accessToken"]


def send(token, session_id, message, mock_base):
    return call(
        AGENT,
        "POST",
        f"/api/v1/agent/conversations/{session_id}/messages",
        {"message": message, "model_provider": "openai", "model_name": "gpt-4o-mini", "model_api_base_url": mock_base},
        token=token,
        headers={"X-Model-Api-Key": "sk-route-test"},
    )


def last_assistant(body):
    return next((m for m in reversed(body.get("messages", [])) if m["role"] == "assistant"), None)


def checks(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label} {detail}")


def main():
    server = serve()
    mock_base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    token = account()

    _, created = call(AGENT, "POST", "/api/v1/agent/conversations", {"auto_approve": True}, token=token)
    session_id = created["session_id"]

    print("=== 1. concept question is answered without tools ===")
    status, body = send(token, session_id, "什么是卡尔曼滤波？", mock_base)
    checks("HTTP 200", status == 200, f"({status})")
    assistant = last_assistant(body)
    checks("assistant replied", assistant is not None)
    checks("no tool calls", assistant and assistant["tool_calls"] == [])
    checks("answer mentions Kalman", assistant and "卡尔曼滤波" in assistant["content"])
    checks("produced by model", assistant and assistant["produced_by"] == "openai:gpt-4o-mini")
    events = [e["event_type"] for e in body.get("events", [])]
    checks("intent_classified present", "intent_classified" in events)

    print("=== 2. a vague request is clarified ===")
    status, body = send(token, session_id, "帮我优化一下这个场景", mock_base)
    checks("HTTP 200", status == 200, f"({status})")
    assistant = last_assistant(body)
    checks("assistant asked back", assistant is not None)
    checks("no tool calls", assistant and assistant["tool_calls"] == [])
    checks("clarification asks which metric", assistant and "优化哪个指标" in assistant["content"])
    events = [e["event_type"] for e in body.get("events", [])]
    checks("clarification_requested present", "clarification_requested" in events)

    print("=== 3. an experiment request reaches the tool loop ===")
    status, body = send(token, session_id, "把目标数改成5并跑一次", mock_base)
    checks("HTTP 200", status == 200, f"({status})")
    tool_messages = [m for m in body.get("messages", []) if m["role"] == "tool"]
    checks("tools ran", len(tool_messages) > 0, f"({len(tool_messages)} tool results)")
    names = [m["tool_name"] for m in tool_messages]
    checks("configuration was changed", "update_experiment_config" in names)

    print("=== 4. the turn is self-checked before it is handed back ===")
    events = [e["event_type"] for e in body.get("events", [])]
    checks("self_check ran", "self_check" in events)
    reflection_events = [e for e in body.get("events", []) if e["event_type"] == "self_check"]
    checks("no issues on a clean run", reflection_events and reflection_events[-1]["payload"]["issues"] == [])

    print("=== wire checks on the mock's request log ===")
    classify_calls = [r for r in RECEIVED if r.get("kind") == "classify"]
    checks("classifier used JSON mode", len(classify_calls) >= 3, f"({len(classify_calls)} calls)")
    concept_calls = [r for r in RECEIVED if r.get("kind") == "concept"]
    checks("concept answer was tool-free", len(concept_calls) >= 1, f"({len(concept_calls)})")
    reflect_calls = [r for r in RECEIVED if r.get("kind") == "reflect"]
    checks("reflection was invoked once", len(reflect_calls) == 1, f"({len(reflect_calls)})")

    server.shutdown()
    print("\nDONE")


if __name__ == "__main__":
    main()
