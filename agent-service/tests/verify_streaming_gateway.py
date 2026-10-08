"""
Verify the streamed model-gateway path parses both providers' SSE correctly:
text deltas arrive as separate events and tool-call arguments are reassembled
across fragments. Uses an inline mock provider, no external service.
"""
import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.model_gateway import ModelCredential, stream_call_with_tools
from app.conversation import AgentMessage


def _openai_stream_body():
    # Two text deltas, then a tool call whose name and JSON arguments arrive in fragments.
    lines = [
        'data: {"choices":[{"delta":{"content":"Hello "}}]}',
        'data: {"choices":[{"delta":{"content":"world."}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"run_","arguments":""}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"simulation","arguments":""}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"","arguments":"{\\"reason\\":"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"","arguments":"\\"go\\"}"}}]}}]}',
        'data: [DONE]',
    ]
    return ("\n".join(lines) + "\n\n").encode()


def _anthropic_stream_body():
    blocks = [
        'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello "}}',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"world."}}',
        'event: content_block_start\ndata: {"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"toolu_1","name":"run_simulation"}}',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\\"reason\\":"}}',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"\\"go\\"}"}}',
        'event: message_stop\ndata: {"type":"message_stop"}',
    ]
    return ("\n".join(blocks) + "\n\n").encode()


class Handler(BaseHTTPRequestHandler):
    protocol = "openai"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.protocol == "anthropic":
            body = _anthropic_stream_body()
        else:
            body = _openai_stream_body()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve(protocol: str) -> HTTPServer:
    Handler.protocol = protocol
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def _collect(protocol: str, endpoint: str) -> tuple[list[str], list[dict]]:
    credential = ModelCredential(
        provider="openai" if protocol == "openai" else "anthropic",
        label="test",
        protocol="anthropic-messages" if protocol == "anthropic" else "openai-compatible",
        model="test-model",
        api_key="sk-test",
        endpoint=endpoint,
        temperature=0.0,
        timeout_seconds=10.0,
    )
    text_deltas: list[str] = []
    tool_calls: list[dict] = []
    async for event in stream_call_with_tools("sys", [AgentMessage(role="user", content="hi")], [], credential):
        if event.kind == "text":
            text_deltas.append(event.text)
        elif event.kind == "tool_calls":
            tool_calls = [c.model_dump() for c in (event.tool_calls or [])]
    return text_deltas, tool_calls


async def main():
    failures = []
    for protocol in ("openai", "anthropic"):
        server = _serve(protocol)
        endpoint = f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
        deltas, calls = await _collect(protocol, endpoint)
        text = "".join(deltas)
        ok_text = text == "Hello world."
        ok_tool = len(calls) == 1 and calls[0]["name"] == "run_simulation" and calls[0]["arguments"] == {"reason": "go"}
        print(f"[{protocol}] text={text!r} (deltas={len(deltas)}) | tool_calls={json.dumps(calls, ensure_ascii=False)}")
        print(f"   text ok={ok_text} | tool ok={ok_tool}")
        if not (ok_text and ok_tool):
            failures.append(protocol)
        server.shutdown()
    print("\nRESULT:", "ALL PASS" if not failures else f"FAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
