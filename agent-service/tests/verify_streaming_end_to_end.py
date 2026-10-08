"""
End-to-end check that the SSE streaming endpoints deliver frames incrementally.

A mock provider with a small per-call latency stands in for a real model. If the stream were
buffered until the turn finished, the first frame and the last would carry the same timestamp;
the assertion here is that they do not, which is the whole point of streaming.

Run with the Java backend on 8080 and the agent service on 8000:

    python tests/verify_streaming_end_to_end.py
"""

import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["MOCK_DELAY_SECONDS"] = "0.35"

from mock_model_server import serve  # noqa: E402


JAVA = "http://127.0.0.1:8080"
AGENT = "http://127.0.0.1:8000"
MOCK_PORT = 8117
MOCK_BASE = f"http://127.0.0.1:{MOCK_PORT}/v1"

FAILURES: list[str] = []


def check(label, condition, detail=""):
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


def account(tag):
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
    _, payload = call(
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
    return payload["data"]["accessToken"]


def read_stream(base, path, body, token, secret):
    """Read the SSE response incrementally, timestamping each frame as it arrives."""
    data = json.dumps(body).encode()
    request = urllib.request.Request(base + path, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", "Bearer " + token)
    request.add_header("X-Model-Api-Key", secret)
    frames = []
    started = time.time()
    with urllib.request.urlopen(request, timeout=120) as response:
        content_type = response.headers.get("Content-Type", "")
        buffer = ""
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace")
            buffer += line
            if line == "\n":
                block = buffer.strip("\n")
                buffer = ""
                if not block.strip():
                    continue
                event, data_text = "message", ""
                for part in block.split("\n"):
                    if part.startswith("event:"):
                        event = part[len("event:"):].strip()
                    elif part.startswith("data:"):
                        data_text = part[len("data:"):].strip()
                try:
                    data = json.loads(data_text) if data_text else None
                except ValueError:
                    data = data_text
                frames.append((event, data, round(time.time() - started, 3)))
    return content_type, frames


def main():
    global MOCK_BASE
    server = serve()
    MOCK_BASE = f"http://127.0.0.1:{server.server_address[1]}/v1"
    token = account("stream")

    print("\n=== 1. message stream arrives frame by frame ===")
    _, created = call(AGENT, "POST", "/api/v1/agent/conversations", {}, token=token)
    session_id = created["session_id"]

    content_type, frames = read_stream(
        AGENT,
        f"/api/v1/agent/conversations/{session_id}/messages/stream",
        {"message": "Raise the target count and run it.", "model_provider": "openai", "model_api_base_url": MOCK_BASE},
        token,
        "sk-stream-secret",
    )

    check("content type is event-stream", content_type.startswith("text/event-stream"), content_type)
    kinds = [kind for kind, _, _ in frames]
    check("first frame is the user message", kinds and kinds[0] == "message", str(kinds[:3]))
    check("last frame is the session", kinds and kinds[-1] == "session", str(kinds[-3:]))
    check(
        "progress frames carried tool calls before the end",
        any(kind == "progress" and data.get("event_type") == "tool_called" for kind, data, _ in frames),
    )
    check(
        "confirmation was requested before approval",
        any(kind == "progress" and data.get("event_type") == "confirmation_requested" for kind, data, _ in frames),
    )

    final = frames[-1][1]
    check("session is authoritative", final["session_id"] == session_id)
    check("session paused for approval", final["status"] == "AWAITING_CONFIRMATION", final["status"])

    # Streaming proof: the first frame and the last must not share a timestamp, because the mock
    # model adds ~350ms of latency per call and there are several calls in the turn.
    first_at = frames[0][2]
    last_at = frames[-1][2]
    check(
        "frames were delivered incrementally, not in one buffered blob",
        (last_at - first_at) >= 0.3,
        f"first={first_at}s last={last_at}s",
    )

    print("\n=== 2. the decision stream continues the same turn ===")
    content_type, decision_frames = read_stream(
        AGENT,
        f"/api/v1/agent/conversations/{session_id}/decision/stream",
        {"approve": True, "model_provider": "openai", "model_api_base_url": MOCK_BASE},
        token,
        "sk-stream-secret",
    )
    decision_kinds = [kind for kind, _, _ in decision_frames]
    check("decision content type is event-stream", content_type.startswith("text/event-stream"))
    check("decision ended with the session", decision_kinds and decision_kinds[-1] == "session")
    decision_final = decision_frames[-1][1]
    check("the run executed after approval", decision_final["last_run_id"] is not None, str(decision_final["last_run_id"])[:8])
    run_message = [m for m in decision_final["messages"] if m.get("tool_name") == "run_simulation"][-1]
    check("evidence came back with the run", bool(run_message["evidence"]))

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
