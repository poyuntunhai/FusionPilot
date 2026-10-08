"""
A stand-in for a model provider, in both protocol families.

Two jobs:

1. Verify the bring-your-own-token path end to end without a real provider. The agent service is
   pointed at this server through `api_base_url` and must forward the user's key here, which the
   request log proves.
2. Behave like an actual agent when the request carries a tool catalog, so the multi-turn loop can
   be exercised over real HTTP: it reads the configuration, patches it, runs a simulation, re-reads
   the metrics, and then answers using the numbers the tool returned - never invented ones.

The second job matters because the interesting failure modes of an agent loop (a paused
confirmation, a declined tool, a transcript that no longer replays) only show up against a model
that actually calls tools in sequence.

Run standalone:  python tests/mock_model_server.py 8099
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

RECEIVED: list[dict] = []
_CALL_COUNTER = {"value": 0}


def _plan_payload() -> dict:
    return {
        "title": "Model-planned radar tracking experiment",
        "goal": "goal",
        "assumptions": ["Two-dimensional discrete-time synthetic scene."],
        "experiment_config": {"targetCount": 3, "simulationSteps": 6, "schedulingPolicy": "PRIORITY"},
        "baselines": ["ROUND_ROBIN", "PRIORITY"],
        "metrics": ["trackingRate", "averagePositionError"],
        "execution_steps": ["Validate the configuration.", "Run the simulation.", "Read the metrics."],
        "expected_outputs": ["A reproducible simulation result."],
        "requires_confirmation": True,
        "recommended_tool": "run_simulation",
    }


def _analysis_payload(metrics: dict) -> dict:
    first_key = next(iter(metrics), None)
    evidence = []
    if first_key is not None:
        evidence.append({"metric": first_key, "value": metrics[first_key], "note": "primary reading"})
    # Deliberately includes a metric that does not exist, to prove the service filters it out.
    evidence.append({"metric": "hallucinatedMetric", "value": 12345, "note": "should be dropped"})
    return {
        "summary": "The run completed; the primary metric is reported below.",
        "evidence": evidence,
        "limitations": ["Single random seed."],
    }


def _safe_json(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def _is_anthropic(body: dict) -> bool:
    tools = body.get("tools") or []
    if tools and isinstance(tools[0], dict) and "input_schema" in tools[0]:
        return True
    return isinstance(body.get("system"), str)


def _tool_history(body: dict) -> list[tuple]:
    """
    Ordered [(tool_name, parsed_result)] for whichever protocol this request used.

    Reading both shapes is what lets one mock cover both conversion paths.
    """
    if _is_anthropic(body):
        names: dict[str, str] = {}
        for message in body.get("messages", []):
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    names[block.get("id")] = block.get("name")
        entries = []
        for message in body.get("messages", []):
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    entries.append((names.get(block.get("tool_use_id")), _safe_json(block.get("content"))))
        return entries

    names = {}
    for message in body.get("messages", []):
        for call in message.get("tool_calls") or []:
            names[call.get("id")] = (call.get("function") or {}).get("name")
    return [
        (names.get(message.get("tool_call_id")), _safe_json(message.get("content")))
        for message in body.get("messages", [])
        if message.get("role") == "tool"
    ]


def _agent_step(entries: list[tuple]) -> tuple:
    """Decide the agent's next move from the tools it has already used."""
    done = [name for name, _ in entries]
    if "get_experiment_config" not in done:
        return "tool", "get_experiment_config", {}
    if "update_experiment_config" not in done:
        return (
            "tool",
            "update_experiment_config",
            {"patch": {"targetCount": 5, "simulationSteps": 12, "fusionMethod": "KALMAN_FILTER"}, "why": "compare trackers"},
        )
    if "run_simulation" not in done:
        return "tool", "run_simulation", {"reason": "Establish the baseline for the chosen tracker."}

    run_payload = None
    for name, payload in reversed(entries):
        if name == "run_simulation":
            run_payload = payload
            break
    result = (run_payload or {}).get("result") or {}
    metrics = result.get("metrics") or {}
    if not run_payload or not run_payload.get("ok"):
        error = (run_payload or {}).get("error") or "the run was not executed"
        return "text", f"The run did not happen: {error}", None
    if "calculate_metrics" not in done:
        return "tool", "calculate_metrics", {}

    error_value = metrics.get("averagePositionError")
    tracking = metrics.get("trackingRate")
    summary = (
        f"The run finished with a mean position error of {error_value} and a tracking rate of {tracking}. "
        "Those are the values the simulation returned."
    )
    return "text", summary, None


def _classify_payload(user_text: str) -> dict:
    """Route a user message the same way the intent classifier is told to."""
    if any(key in user_text for key in ("什么是", "区别", "怎么算", "原理", "解释", "是什么")):
        return {"action": "concept_qa", "question": ""}
    if "优化" in user_text and "指标" not in user_text:
        return {"action": "clarify", "question": "你想先优化哪个指标：位置误差还是跟踪率？"}
    if any(key in user_text for key in ("对比", "比较", "敏感性", "找出")):
        return {"action": "explore", "question": ""}
    return {"action": "experiment", "question": ""}


def _sequence_payload() -> dict:
    """A multi-step comparison plan, used to exercise the exploratory route."""
    return {
        "goal": "对比置信度加权平均与卡尔曼滤波的定位精度",
        "rationale": "同一场景下各跑一次，直接比较平均位置误差。",
        "steps": [
            {"summary": "把融合方法设为置信度加权平均", "tool": "update_experiment_config", "arguments": {"patch": {"fusionMethod": "WEIGHTED_AVERAGE"}}},
            {"summary": "跑加权平均基线", "tool": "run_simulation", "arguments": {"reason": "baseline"}},
            {"summary": "把融合方法设为卡尔曼滤波", "tool": "update_experiment_config", "arguments": {"patch": {"fusionMethod": "KALMAN_FILTER"}}},
            {"summary": "跑卡尔曼滤波对比", "tool": "run_simulation", "arguments": {"reason": "compare"}},
        ],
    }


def _request_kind(system_text: str, has_tools: bool) -> str:
    """Label a request by which agent-service subsystem issued it, for wire-level assertions."""
    if "意图路由" in system_text:
        return "classify"
    if "不需要你运行仿真" in system_text:
        return "concept"
    if "实验规划器" in system_text:
        return "planner"
    if "自检模块" in system_text:
        return "reflect"
    if "analysis module" in system_text:
        return "analysis"
    return "agent" if has_tools else "other"


def _grounded(system_text: str) -> bool:
    """
    Whether the request actually carried retrieved material.

    The block headers are the only reliable marker. Both prompts *talk about* the material, so
    matching on the words "知识库" or "参考材料" would report every request as grounded — which is
    exactly the bug this function exists to avoid, and the end-to-end check catches it.
    """
    return "## 知识库" in system_text or "## 参考材料" in system_text


def _concept_answer(grounded: bool) -> str:
    """
    The concept reply, as a real model would give it with and without the reference material.

    With the material the answer quotes a fact that only exists in the corpus — the fusion layer
    sees the ground truth, so Kalman is the only method that estimates velocity. Asserting that
    sentence travels all the way to the transcript is what proves the retrieval path is connected;
    a generic answer would pass even if the material never arrived.
    """
    if grounded:
        return (
            "按平台资料，卡尔曼滤波是五种融合方法里唯一真正估计速度的方法，"
            "其余方法上报的速度是从目标真值复制的，因此那不是估计量。"
        )
    return "平台资料里没有与这个问题对应的小节，我不能凭一般常识替它作答。"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        """Silence per-request logging."""

    def do_POST(self):  # noqa: N802 - required by BaseHTTPRequestHandler
        # Optional per-call latency, so streaming tests can observe frames arriving over time
        # instead of in one instant burst.
        delay = float(os.environ.get("MOCK_DELAY_SECONDS", "0") or "0")
        if delay > 0:
            time.sleep(delay)
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        body = json.loads(raw)
        messages = body.get("messages", [])
        system_text = " ".join(
            message.get("content", "") for message in messages if message.get("role") == "system"
        )
        anthropic = _is_anthropic(body)
        has_tools = bool(body.get("tools"))
        if anthropic and not system_text:
            system_text = str(body.get("system") or "")

        entries = _tool_history(body) if has_tools else []
        RECEIVED.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization", ""),
                "api_key_header": self.headers.get("x-api-key", ""),
                "model": body.get("model"),
                "response_format": body.get("response_format"),
                "protocol": "anthropic" if anthropic else "openai",
                "has_tools": has_tools,
                "tool_names": [
                    (tool.get("name") or (tool.get("function") or {}).get("name"))
                    for tool in (body.get("tools") or [])
                ],
                "tools_used": [name for name, _ in entries],
                "system_has_state": "working_config" in system_text,
                # Whether the platform's reference material was put in front of the model for this
                # call. Detected by the injected block header (see agent_graph.KNOWLEDGE_BLOCK_HEADER
                # / REFERENCE_BLOCK_HEADER), not by the word "knowledge": the prompts mention the
                # material in prose, so a prose mention would read as a false positive and the check
                # would pass even when nothing was retrieved.
                "has_knowledge": _grounded(system_text),
                "kind": _request_kind(system_text, has_tools),
            }
        )

        # Intent routing: the graph's `classify` node makes a plain JSON call (no tools, no
        # stream). Answer it from the user's message so the routing is exercised end to end.
        if "意图路由" in system_text:
            user_content = next(
                (message.get("content", "") for message in messages if message.get("role") == "user"),
                "{}",
            )
            try:
                user_text = json.loads(user_content).get("message", "")
            except (TypeError, ValueError):
                user_text = user_content
            self._send(
                {"choices": [{"message": {"role": "assistant", "content": json.dumps(_classify_payload(user_text), ensure_ascii=False)}}]}
            )
            return

        # Experiment planning: the `plan_experiment` node asks for a multi-step sequence.
        if "实验规划器" in system_text:
            self._send({"choices": [{"message": {"role": "assistant", "content": json.dumps(_sequence_payload(), ensure_ascii=False)}}]})
            return

        # Concept answer: no tools, but streamed token by token.
        if "不需要你运行仿真" in system_text:
            if body.get("stream") and not anthropic:
                self._respond_concept_stream_openai(grounded=_grounded(system_text))
            else:
                self._send(
                    {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": _concept_answer(_grounded(system_text)),
                                }
                            }
                        ]
                    }
                )
            return

        # Self-reflection: the graph's `reflect` node audits the agent's own prose with a plain
        # JSON call. Approve the turn unless the prose claims "cache", which the deterministic
        # layer already tells the model is not evidence of anything.
        if "自检模块" in system_text:
            narrative = ""
            try:
                narrative = json.loads(messages[-1].get("content", "{}")).get("narrative", "")
            except (TypeError, ValueError):
                pass
            if "缓存" in narrative:
                payload = {
                    "supported": False,
                    "problem": "把确定性复现误判成了缓存。",
                    "correction": "相同配置与随机种子必然得到相同结果，这是确定性复现，不是缓存。",
                }
            else:
                payload = {"supported": True, "problem": "", "correction": ""}
            self._send({"choices": [{"message": {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)}}]})
            return

        if has_tools:
            # Both protocol families are streamed here, because the tool loop now calls
            # ``stream_call_with_tools`` for both. An Anthropic request that was answered with a
            # plain JSON body would be unparseable by the Anthropic SSE reader, so the loop would
            # see an empty reply with no tool calls and the turn would end silently — which is
            # exactly what happened before this branch existed.
            if not body.get("stream"):
                self._respond_agent(anthropic, entries)
            elif anthropic:
                self._respond_agent_stream_anthropic(entries)
            else:
                self._respond_agent_stream_openai(entries)
            return

        if "analysis module" in system_text:
            user_text = next(
                (message.get("content", "") for message in messages if message.get("role") == "user"),
                "{}",
            )
            metrics = json.loads(user_text).get("metrics", {})
            content = json.dumps(_analysis_payload(metrics))
        elif "connectivity probe" in system_text:
            content = "OK"
        else:
            content = json.dumps(_plan_payload())

        self._send({"choices": [{"message": {"role": "assistant", "content": content}}]})

    def _respond_concept_stream_openai(self, grounded: bool = True) -> None:
        """Stream a tool-free concept answer, split into chunks with a pause between them."""
        answer = _concept_answer(grounded)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def frame(obj: dict) -> None:
            self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()

        for i in range(0, len(answer), 4):
            frame({"choices": [{"delta": {"content": answer[i : i + 4]}}]})
            time.sleep(0.04)
        frame({"choices": [{"delta": {}, "finish_reason": "stop"}]})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _respond_agent_stream_openai(self, entries: list[tuple]) -> None:
        """Stream an OpenAI-format reply, splitting prose into chunks with a pause between them."""
        kind, name, arguments = _agent_step(entries)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def frame(obj: dict) -> None:
            self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()

        if kind == "text":
            for i in range(0, len(name), 3):
                frame({"choices": [{"delta": {"content": name[i : i + 3]}}]})
                time.sleep(0.08)
        else:
            _CALL_COUNTER["value"] += 1
            frame(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": f"mock_call_{_CALL_COUNTER['value']}",
                                        "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
                                    }
                                ]
                            }
                        }
                    ]
                }
            )
        frame({"choices": [{"delta": {}, "finish_reason": "tool_calls" if kind == "tool" else "stop"}]})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _respond_agent_stream_anthropic(self, entries: list[tuple]) -> None:
        """
        Stream an Anthropic messages-API reply, in the event shape the gateway parses.

        Tool arguments arrive as ``input_json_delta`` fragments, which is how the real API sends
        them; splitting the JSON mid-object is deliberate, so the accumulation path is exercised
        rather than a single convenient whole-object delta.
        """
        kind, name, arguments = _agent_step(entries)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def frame(event_type: str, payload: dict) -> None:
            line = "event: " + event_type + "\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            self.wfile.write(line.encode())
            self.wfile.flush()

        if kind == "text":
            frame("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
            for i in range(0, len(name), 3):
                frame("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": name[i : i + 3]}})
                time.sleep(0.05)
        else:
            _CALL_COUNTER["value"] += 1
            frame(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": f"mock_call_{_CALL_COUNTER['value']}",
                        "name": name,
                    },
                },
            )
            partial = json.dumps(arguments, ensure_ascii=False)
            for i in range(0, len(partial), 20):
                frame(
                    "content_block_delta",
                    {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": partial[i : i + 20]}},
                )
        frame("message_stop", {"type": "message_stop"})

    def _respond_agent(self, anthropic: bool, entries: list[tuple]) -> None:
        kind, name, arguments = _agent_step(entries)
        if kind == "text":
            if anthropic:
                self._send({"content": [{"type": "text", "text": name}]})
            else:
                self._send({"choices": [{"message": {"role": "assistant", "content": name}}]})
            return

        _CALL_COUNTER["value"] += 1
        call_id = f"mock_call_{_CALL_COUNTER['value']}"
        if anthropic:
            self._send(
                {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": arguments}]}
            )
            return
        self._send(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": name,
                                        "arguments": json.dumps(arguments, ensure_ascii=False),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )

    def _send(self, payload: dict) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def serve(port: int = 0) -> HTTPServer:
    """
    Start the mock on ``port``, or on a free ephemeral port when 0 is passed.

    Callers should read ``server.server_address[1]`` for the real port. Defaulting to an ephemeral
    port matters on Windows: ``SO_REUSEADDR`` there happily lets a second process bind a port that
    is already serving, and the requests then go to the other process, which makes a test pass
    while quietly exercising the wrong server.
    """
    server = HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    listen_port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print(f"mock model server listening on http://127.0.0.1:{listen_port}")
    serve(listen_port)
    threading.Event().wait()
