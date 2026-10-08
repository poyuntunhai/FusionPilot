"""
End-to-end check for autonomous experiment planning over real HTTP.

One exploratory goal is sent. The agent should design a multi-step sequence, present it as one
pending batch, and - once approved - run every step in order. The mock's request log proves the
planner was actually called.
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
        with urllib.request.urlopen(req, timeout=90) as resp:
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

    username = "plan" + str(random.randint(100000, 999999))
    cid, answer = captcha()
    call(JAVA, "POST", "/api/v1/auth/register", {
        "username": username,
        "email": username + "@t.local",
        "password": "ProbePass12345",
        "displayName": "Plan",
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


def checks(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label} {detail}")


def main():
    server = serve()
    mock_base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    token = account()

    _, created = call(AGENT, "POST", "/api/v1/agent/conversations", {}, token=token)
    session_id = created["session_id"]

    print("=== 1. an exploratory goal is planned, not executed ===")
    status, body = call(
        AGENT,
        "POST",
        f"/api/v1/agent/conversations/{session_id}/messages",
        {"message": "对比加权平均和卡尔曼滤波的定位精度", "model_provider": "openai", "model_name": "gpt-4o-mini", "model_api_base_url": mock_base},
        token=token,
        headers={"X-Model-Api-Key": "sk-plan-test"},
    )
    checks("HTTP 200", status == 200, f"({status})")
    checks("paused for approval", body.get("status") == "AWAITING_CONFIRMATION")
    sequence = body.get("sequence")
    checks("a sequence was stored", bool(sequence))
    checks("sequence has 4 steps", sequence and len(sequence["steps"]) == 4, f"({len(sequence['steps']) if sequence else 0})")
    pending = body.get("pending") or {}
    calls = pending.get("tool_calls") or []
    checks("all steps are one pending batch", len(calls) == 4, f"({len(calls)} calls)")
    checks("batch mixes updates and runs", [c["name"] for c in calls].count("run_simulation") == 2)
    tool_messages = [m for m in body.get("messages", []) if m["role"] == "tool"]
    checks("nothing ran before approval", tool_messages == [])

    print("=== 2. approving the plan runs every run step ===")
    status, approved = call(
        AGENT,
        "POST",
        f"/api/v1/agent/conversations/{session_id}/decision",
        {"approve": True, "model_provider": "openai", "model_name": "gpt-4o-mini", "model_api_base_url": mock_base},
        token=token,
        headers={"X-Model-Api-Key": "sk-plan-test"},
    )
    checks("HTTP 200", status == 200, f"({status})")
    ran = [m for m in approved.get("messages", []) if m["role"] == "tool" and m.get("tool_name") == "run_simulation"]
    checks("both plan runs executed", len(ran) == 2, f"({len(ran)} runs)")
    checks("runs carry a run id", all(m.get("run_id") for m in ran))

    print("=== wire checks ===")
    planner_calls = [r for r in RECEIVED if r.get("kind") == "planner"]
    checks("planner was called once", len(planner_calls) == 1, f"({len(planner_calls)})")

    server.shutdown()
    print("\nDONE")


if __name__ == "__main__":
    main()
