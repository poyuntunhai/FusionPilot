"""
End-to-end check of the bring-your-own-token path against the running services.

Starts the mock OpenAI-compatible endpoint from mock_model_server.py, then drives the live
agent service (127.0.0.1:8000) and Java backend (127.0.0.1:8080) exactly as the browser does.

Run:  .venv/Scripts/python.exe tests/verify_byok_end_to_end.py
"""

import json
import pathlib
import random
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import mock_model_server  # noqa: E402

JAVA = "http://127.0.0.1:8080"
AGENT = "http://127.0.0.1:8000"
MOCK = "http://127.0.0.1:8099/v1/chat/completions"
SECRET = "sk-user-supplied-token-abc123"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"  [{mark}] {label}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)


def call(base: str, method: str, path: str, body=None, token=None, model_key=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    if model_key:
        request.add_header("X-Model-Api-Key", model_key)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
            return response.status, (json.loads(raw) if raw else {}), raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw), raw
        except Exception:
            return exc.code, {}, raw


def captcha():
    _, payload, _ = call(AGENT if False else JAVA, "GET", "/api/v1/auth/captcha")
    challenge = payload["data"]
    numbers = [int(n) for n in re.findall(r"-?\d+", challenge["question"])]
    answer = numbers[0] + numbers[1]
    return challenge["challengeId"], str(answer)


def make_account():
    username = "byok%d" % random.randint(100000, 999999)
    cid, answer = captcha()
    call(JAVA, "POST", "/api/v1/auth/register", {
        "username": username, "email": username + "@t.local", "password": "ProbePass12345",
        "displayName": "BYOK", "captchaId": cid, "captchaAnswer": answer,
    })
    cid, answer = captcha()
    _, payload, _ = call(JAVA, "POST", "/api/v1/auth/login", {
        "login": username, "password": "ProbePass12345", "captchaId": cid, "captchaAnswer": answer,
    })
    return payload["data"]["accessToken"]


print("=== 0. 启动模拟模型端点 ===")
mock_server = mock_model_server.serve()
MOCK = f"http://127.0.0.1:{mock_server.server_address[1]}/v1/chat/completions"
time.sleep(0.5)
print(f"  mock listening on {MOCK}")

token = make_account()
print("\n=== 1. 连接测试：请求头里的令牌必须被转发到模型端点 ===")
mock_model_server.RECEIVED.clear()
status, payload, _ = call(AGENT, "POST", "/api/v1/agent/models/test",
                          {"provider": "openai", "model": "gpt-4o-mini", "api_base_url": MOCK},
                          token=token, model_key=SECRET)
check("连接测试返回 200", status == 200, f"status={status} body={json.dumps(payload)[:200]}")
check("回复内容为 OK", payload.get("reply") == "OK", f"reply={payload.get('reply')!r}")
sent = mock_model_server.RECEIVED[-1] if mock_model_server.RECEIVED else {}
check("用户令牌以 Bearer 形式转发", sent.get("authorization") == "Bearer " + SECRET,
      f"authorization={sent.get('authorization')!r}")

print("\n=== 2. 无令牌时的连接测试 ===")
mock_model_server.RECEIVED.clear()
status, payload, _ = call(AGENT, "POST", "/api/v1/agent/models/test", {"provider": "openai"}, token=token)
check("缺少令牌返回 400", status == 400, f"status={status}")
check("错误码为 MODEL_API_KEY_MISSING", payload.get("detail", {}).get("code") == "MODEL_API_KEY_MISSING")
check("没有向模型端点发出请求", len(mock_model_server.RECEIVED) == 0)

print("\n=== 3. 用自带令牌生成方案（模型真实参与） ===")
mock_model_server.RECEIVED.clear()
status, trace, raw = call(AGENT, "POST", "/api/v1/agent/sessions",
                          {"goal": "比较两种调度策略在多目标场景下的跟踪表现",
                           "model_provider": "openai", "model_name": "gpt-4o-mini",
                           "model_api_base_url": MOCK},
                          token=token, model_key=SECRET)
check("创建会话返回 200", status == 200, f"status={status}")
plan = trace.get("plan", {})
check("规划者标记为模型", plan.get("planner") == "openai", f"planner={plan.get('planner')!r}")
check("模型名称正确", plan.get("model") == "gpt-4o-mini", f"model={plan.get('model')!r}")
check("方案标题来自模型", plan.get("title") == "Model-planned radar tracking experiment",
      f"title={plan.get('title')!r}")
check("推荐工具已透传", plan.get("recommended_tool") == "run_simulation")
check("实验配置来自模型", plan.get("experiment_config", {}).get("schedulingPolicy") == "PRIORITY")
check("令牌未出现在响应中", SECRET not in raw)
check("模型请求携带了令牌", any(r["authorization"] == "Bearer " + SECRET for r in mock_model_server.RECEIVED))

print("\n=== 4. 确认并执行工具，观察是否由模型解读结果 ===")
trace_id = trace["trace_id"]
status, _, _ = call(AGENT, "POST", f"/api/v1/agent/sessions/{trace_id}/confirm", token=token)
check("确认返回 200", status == 200, f"status={status}")

mock_model_server.RECEIVED.clear()
status, result, raw = call(AGENT, "POST", f"/api/v1/agent/sessions/{trace_id}/execute",
                           {"tool_name": "run_simulation", "model_provider": "openai",
                            "model_name": "gpt-4o-mini", "model_api_base_url": MOCK},
                           token=token, model_key=SECRET)
check("执行工具返回 200", status == 200, f"status={status}")
check("确实调用了模型做解读", len(mock_model_server.RECEIVED) > 0)
analysis = result.get("analysis") or {}
check("解读来源标记为模型", analysis.get("produced_by") == "openai:gpt-4o-mini",
      f"produced_by={analysis.get('produced_by')!r}")
check("解读摘要来自模型", analysis.get("summary", "").startswith("The run completed"),
      f"summary={analysis.get('summary','')[:60]!r}")
metric_names = [item["metric"] for item in analysis.get("evidence", [])]
check("模型编造的指标被过滤掉", "hallucinatedMetric" not in metric_names, f"evidence={metric_names}")
check("保留下来的指标值取自 Java 后端",
      all(item.get("source") == "java-backend-result" for item in analysis.get("evidence", [])))
check("仿真结果本身来自 Java", isinstance(result.get("result", {}).get("metrics"), dict))

print("\n=== 5. 令牌绝不落库 ===")
check("执行响应中没有令牌", SECRET not in raw)
status, stored, stored_raw = call(AGENT, "GET", f"/api/v1/agent/sessions/{trace_id}", token=token)
check("可从 Java 侧恢复轨迹", status == 200, f"status={status}")
check("落库的轨迹里没有令牌", SECRET not in stored_raw)

print("\n=== 6. 无令牌时明确回退，不假装用了模型 ===")
status, fallback_trace, _ = call(AGENT, "POST", "/api/v1/agent/sessions",
                                 {"goal": "比较两种调度策略在多目标场景下的跟踪表现",
                                  "model_provider": "deepseek", "model_name": "deepseek-chat"},
                                 token=token)
fallback_plan = fallback_trace.get("plan", {})
check("标记为规则回退", fallback_plan.get("planner") == "rule-fallback",
      f"planner={fallback_plan.get('planner')!r}")
check("给出了回退原因", bool(fallback_plan.get("planning_note")),
      f"note={fallback_plan.get('planning_note')!r}")

print("\n" + "=" * 60)
if failures:
    print(f"FAILED ({len(failures)}):")
    for item in failures:
        print("   -", item)
    sys.exit(1)
print("ALL CHECKS PASSED")
