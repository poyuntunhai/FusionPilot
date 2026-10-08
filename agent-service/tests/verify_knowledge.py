"""
End-to-end check for grounded concept answers, over real HTTP.

The unit tests prove retrieval picks the right section. This proves the *path* is connected:
corpus file -> index -> prompt -> model -> transcript -> citation chips. Those are separate
failures, and only the last one is visible to a user.

Four turns through the live agent service, with the mock provider standing in for a real model:

1. a question the corpus answers        -> a grounded answer that quotes the corpus
2. a question the corpus cannot answer  -> an explicitly ungrounded answer, no citations
3. an exploratory goal                  -> the planner is handed the reference material too
4. the search endpoint, queried directly

The mock's request log is inspected as well, because a right answer is not proof: a model can be
right by luck. ``has_knowledge`` on the wire is the proof that the material actually arrived.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mock_model_server import RECEIVED, serve  # noqa: E402

JAVA = "http://127.0.0.1:8080"
AGENT = "http://127.0.0.1:8000"

# A fact that exists only in the corpus. If this sentence reaches the client, the material the
# answer was built from came from the knowledge base and not from the model's priors.
CORPUS_ONLY_FACT = "唯一真正估计速度"


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

    username = "know" + str(random.randint(100000, 999999))
    cid, answer = captcha()
    call(JAVA, "POST", "/api/v1/auth/register", {
        "username": username,
        "email": username + "@t.local",
        "password": "ProbePass12345",
        "displayName": "Know",
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
        headers={"X-Model-Api-Key": "sk-knowledge-test"},
    )


def last_assistant(body):
    return next((m for m in reversed(body.get("messages", [])) if m["role"] == "assistant"), None)


def events(body):
    return [e["event_type"] for e in body.get("events", [])]


def last_event(body, event_type):
    return next((e for e in reversed(body.get("events", [])) if e["event_type"] == event_type), None)


def checks(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label} {detail}")
    return bool(condition)


def main():
    server = serve()
    mock_base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    token = account()
    passed = True

    _, created = call(AGENT, "POST", "/api/v1/agent/conversations", {"auto_approve": True}, token=token)
    session_id = created["session_id"]

    print("=== 1. a question the corpus answers is answered from the corpus ===")
    status, body = send(token, session_id, "什么是卡尔曼滤波？", mock_base)
    passed &= checks("HTTP 200", status == 200, f"({status})")
    assistant = last_assistant(body)
    passed &= checks("no tool calls", assistant is not None and assistant["tool_calls"] == [])
    passed &= checks(
        "the answer quotes a corpus-only fact",
        assistant is not None and CORPUS_ONLY_FACT in assistant["content"],
    )
    passed &= checks("knowledge_retrieved emitted", "knowledge_retrieved" in events(body))
    retrieved = last_event(body, "knowledge_retrieved") or {}
    passed &= checks("marked as grounded", retrieved.get("payload", {}).get("grounded") is True)
    matches = retrieved.get("payload", {}).get("matches") or []
    passed &= checks(
        "the Kalman section was the source",
        bool(matches) and matches[0]["chunk_id"] == "fusion-methods#kalman_filter",
        f"({matches[0]['chunk_id'] if matches else 'none'})",
    )
    passed &= checks(
        "citations persisted on the message",
        assistant is not None and assistant["knowledge"] and assistant["knowledge"][0]["title"] == "卡尔曼滤波",
    )

    print("=== 2. a question the corpus cannot answer is not improvised ===")
    status, body = send(token, session_id, "解释一下今天北京的天气怎么样", mock_base)
    passed &= checks("HTTP 200", status == 200, f"({status})")
    assistant = last_assistant(body)
    passed &= checks(
        "the answer states it has no material",
        assistant is not None and "没有与这个问题对应的小节" in assistant["content"],
        f"(got {assistant['content'][:60]!r})" if assistant else "(no assistant message)",
    )
    retrieved = last_event(body, "knowledge_retrieved") or {}
    passed &= checks("not grounded", retrieved.get("payload", {}).get("grounded") is False)
    passed &= checks("no citations attached", assistant is not None and assistant["knowledge"] == [])

    print("=== 3. the planner is handed the reference material too ===")
    status, body = send(token, session_id, "对比卡尔曼滤波和加权平均的定位精度", mock_base)
    passed &= checks("HTTP 200", status == 200, f"({status})")
    passed &= checks("a plan was proposed", "plan_created" in events(body))
    plan = body.get("sequence") or {}
    passed &= checks("the plan has steps", len(plan.get("steps") or []) >= 2, f"({len(plan.get('steps') or [])} steps)")
    planner_calls = [r for r in RECEIVED if r.get("kind") == "planner"]
    passed &= checks("planner ran", len(planner_calls) >= 1)
    passed &= checks(
        "planner received the material",
        bool(planner_calls) and all(r.get("has_knowledge") for r in planner_calls),
    )

    print("=== 4. the search endpoint answers directly ===")
    query = urllib.parse.quote("资源利用率")
    status, payload = call(AGENT, "GET", f"/api/v1/agent/knowledge/search?q={query}&limit=2", token=token)
    passed &= checks("HTTP 200", status == 200, f"({status})")
    passed &= checks("corpus was indexed", (payload.get("corpus") or {}).get("chunk_count", 0) >= 25)
    matches = payload.get("matches") or []
    passed &= checks("a section matched", bool(matches))
    passed &= checks(
        "the utilisation section ranked first",
        bool(matches) and matches[0]["title"] == "资源利用率",
        f"({matches[0]['title'] if matches else 'none'})",
    )
    passed &= checks(
        "an excerpt is returned",
        bool(matches) and "availableResources" in matches[0].get("excerpt", ""),
    )

    print("=== wire checks on the mock's request log ===")
    concept_calls = [r for r in RECEIVED if r.get("kind") == "concept"]
    passed &= checks("both concept turns reached the model", len(concept_calls) == 2, f"({len(concept_calls)})")
    grounded_count = sum(1 for r in concept_calls if r.get("has_knowledge"))
    passed &= checks(
        "exactly one concept call carried the material",
        grounded_count == 1,
        f"({grounded_count} of {len(concept_calls)})",
    )

    server.shutdown()
    print("\n" + ("DONE - all checks passed" if passed else "DONE - FAILURES ABOVE"))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
