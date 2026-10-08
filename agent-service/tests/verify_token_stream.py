"""
Verify token-level streaming end to end over real HTTP:
a mock provider streams prose in chunks, and the agent service must forward them
as distinct `token` progress frames that the UI renders incrementally.
"""
import asyncio
import json
import os
import re
import sys
import urllib.error
import urllib.request

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.mock_model_server import serve  # noqa: E402

JAVA = "http://127.0.0.1:8080"
AGENT = "http://127.0.0.1:8000"
SECRET = "sk-token-stream-secret"


def call(base, method, path, body=None, token=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as err:
        raw = err.read().decode()
        try:
            return err.code, json.loads(raw)
        except ValueError:
            return err.code, {"raw": raw}


def captcha():
    _, payload = call(JAVA, "GET", "/api/v1/auth/captcha")
    data = payload["data"]
    nums = [int(v) for v in re.findall(r"-?\d+", data["question"])]
    ans = nums[0] + nums[1] if "+" in data["question"] else nums[0] - nums[1] if "-" in data["question"] else nums[0] * nums[1]
    return data["challengeId"], str(ans)


def account():
    username = "tk" + str(os.getpid()) + str(int.from_bytes(os.urandom(3), "big"))
    challenge, ans = captcha()
    call(JAVA, "POST", "/api/v1/auth/register", {"username": username, "email": username + "@t.local", "password": "ProbePass12345", "displayName": "TK", "captchaId": challenge, "captchaAnswer": ans})
    challenge, ans = captcha()
    _, payload = call(JAVA, "POST", "/api/v1/auth/login", {"login": username, "password": "ProbePass12345", "captchaId": challenge, "captchaAnswer": ans})
    return payload["data"]["accessToken"]


async def main() -> int:
    server = serve()
    mock_base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    token = account()
    _, created = call(AGENT, "POST", "/api/v1/agent/conversations", {"auto_approve": True}, token=token)
    session_id = created["session_id"]

    body = {"message": "Run the experiment.", "model_provider": "openai", "model_name": "gpt-4o-mini", "model_api_base_url": mock_base}
    url = f"{AGENT}/api/v1/agent/conversations/{session_id}/messages/stream"
    token_frames = []
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}", "X-Model-Api-Key": SECRET, "X-Model-Api-Base": mock_base},
        ) as resp:
            raw = (await resp.aread()).decode("utf-8", "replace")
    for frame in raw.split("\n\n"):
        if 'event: progress' in frame and '"event_type": "token"' in frame:
            match = re.search(r'"text":\s*"(.*?)"', frame)
            if match:
                token_frames.append(json.loads('"' + match.group(1) + '"'))

    print("token 帧数量:", len(token_frames))
    print("拼接文本   :", repr("".join(token_frames)))
    ok = len(token_frames) > 1
    print("RESULT     :", "PASS (token 逐帧到达)" if ok else "FAIL (没有逐帧 token)")
    server.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
