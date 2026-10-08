import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from .config import (
    MODEL_API_BASE_URL,
    MODEL_API_KEY,
    MODEL_FALLBACK_TO_RULE,
    MODEL_NAME,
    MODEL_TEMPERATURE,
    MODEL_TIMEOUT_SECONDS,
    MODEL_PROVIDER,
)
from .conversation import (
    AgentMessage,
    ToolCallRecord,
    to_anthropic_messages,
    to_openai_messages,
)


class ModelGatewayError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProviderPreset:
    provider: str
    label: str
    protocol: str
    endpoint: str
    default_model: str
    model_options: tuple[str, ...]
    # Models that are permanently free (not just a sign-up grant). Shown as "免费" in the UI.
    free_models: tuple[str, ...] = ()


PROVIDER_PRESETS = {
    "openai": ProviderPreset(
        "openai",
        "OpenAI",
        "openai-compatible",
        "https://api.openai.com/v1/chat/completions",
        "gpt-5.4-mini",
        (
            "gpt-5.5-pro",
            "gpt-5.5",
            "gpt-5.4-pro",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
            "gpt-5.3-codex",
            "gpt-5.2",
            "gpt-5.1",
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "o3",
            "o3-mini",
            "o4-mini",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4o",
            "gpt-4o-mini",
        ),
    ),
    "anthropic": ProviderPreset(
        "anthropic",
        "Claude",
        "anthropic-messages",
        "https://api.anthropic.com/v1/messages",
        "claude-sonnet-5",
        (
            "claude-fable-5-1",
            "claude-opus-5-5",
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-sonnet-5-5",
            "claude-haiku-4-5",
        ),
    ),
    "deepseek": ProviderPreset(
        "deepseek",
        "DeepSeek",
        "openai-compatible",
        "https://api.deepseek.com/chat/completions",
        "deepseek-v4-flash",
        ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"),
    ),
    "qwen": ProviderPreset(
        "qwen",
        "Qwen",
        "openai-compatible",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "qwen-plus",
        (
            "qwen3.8-max",
            "qwen3.7-max",
            "qwen3.7-plus",
            "qwen3.7-flash",
            "qwen3.6-max-preview",
            "qwen3.6-plus",
            "qwen3.6-flash",
            "qwen3-max",
            "qwen3-plus",
            "qwen-plus",
            "qwen-max",
            "qwen-flash",
            "qwen-turbo",
            "qwen-long",
        ),
    ),
    "zhipu": ProviderPreset(
        "zhipu",
        "Zhipu",
        "openai-compatible",
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "glm-4-flash",
        (
            "glm-4-flash",
            "glm-z1-flash",
            "glm-4",
            "glm-4-plus",
            "glm-5",
            "glm-5-turbo",
            "glm-5.2",
        ),
        ("glm-4-flash", "glm-z1-flash"),
    ),
}


@dataclass(frozen=True)
class ModelCredential:
    """
    Everything one model call needs.

    This object is built per request and never serialised: it is deliberately not a pydantic
    model and is never placed on a trace, an event payload, or an API response. The API key
    travels in a request header so it cannot end up in a persisted session snapshot.
    """

    provider: str
    label: str
    protocol: str
    model: str
    api_key: str
    endpoint: str
    temperature: float
    timeout_seconds: float


def _environment_key(provider: str) -> str:
    """The server-side key only ever applies to the provider it was configured for."""
    return MODEL_API_KEY if provider == MODEL_PROVIDER else ""


def _environment_endpoint(provider: str) -> str:
    return MODEL_API_BASE_URL if provider == MODEL_PROVIDER else ""


def _environment_model(provider: str) -> str:
    return MODEL_NAME if provider == MODEL_PROVIDER else ""


def has_credentials(provider: str, api_key: str | None = None) -> bool:
    return bool((api_key or "").strip()) or bool(_environment_key(provider))


def resolve_credential(
    provider_name: str | None = None,
    model_name: str | None = None,
    api_key: str | None = None,
    api_base_url: str | None = None,
) -> ModelCredential:
    """
    Resolve the provider, model, key and endpoint for one call.

    A key supplied with the request always wins, which is what lets a user bring their own token
    for any supported provider. The environment key remains a fallback, but only for the single
    provider the server was configured with.
    """
    provider = (provider_name or MODEL_PROVIDER or "rule").strip().lower()
    if provider == "rule":
        raise ModelGatewayError(
            "MODEL_DISABLED",
            "Rule-based mode does not call an external model.",
        )
    preset = PROVIDER_PRESETS.get(provider)
    if preset is None:
        raise ModelGatewayError(
            "MODEL_PROVIDER_UNSUPPORTED",
            f"Unsupported model provider: {provider}",
        )

    resolved_key = (api_key or "").strip() or _environment_key(provider)
    if not resolved_key:
        raise ModelGatewayError(
            "MODEL_API_KEY_MISSING",
            f"No API key available for provider: {provider}",
        )

    return ModelCredential(
        provider=provider,
        label=preset.label,
        protocol=preset.protocol,
        model=(model_name or "").strip() or _environment_model(provider) or preset.default_model,
        api_key=resolved_key,
        endpoint=(api_base_url or "").strip() or _environment_endpoint(provider) or preset.endpoint,
        temperature=MODEL_TEMPERATURE,
        timeout_seconds=MODEL_TIMEOUT_SECONDS,
    )


def provider_catalog(api_key: str | None = None) -> list[dict[str, Any]]:
    supplied = bool((api_key or "").strip())
    return [
        {
            "provider": preset.provider,
            "label": preset.label,
            "protocol": preset.protocol,
            "defaultModel": preset.default_model,
            "modelOptions": list(preset.model_options),
            "freeModels": list(preset.free_models),
            # Callable when the caller brought a key, or when the server holds one for exactly
            # this provider. `serverConfigured` is kept separate so the UI can explain which.
            "configured": supplied or bool(_environment_key(preset.provider)),
            "serverConfigured": bool(_environment_key(preset.provider)),
        }
        for preset in PROVIDER_PRESETS.values()
    ]


def current_provider(
    provider_name: str | None = None,
    model_name: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    provider = (provider_name or MODEL_PROVIDER or "rule").strip().lower()
    requested_model = (model_name or "").strip()
    if provider == "rule":
        return {
            "provider": "rule",
            "label": "Rule-based Agent",
            "protocol": "local",
            "model": None,
            "configured": True,
            "serverConfigured": True,
            "fallbackToRule": MODEL_FALLBACK_TO_RULE,
        }
    preset = PROVIDER_PRESETS.get(provider)
    if preset is None:
        raise ModelGatewayError(
            "MODEL_PROVIDER_UNSUPPORTED",
            f"Unsupported model provider: {provider}",
        )
    return {
        "provider": preset.provider,
        "label": preset.label,
        "protocol": preset.protocol,
        "model": requested_model or _environment_model(provider) or preset.default_model,
        "configured": has_credentials(provider, api_key),
        "serverConfigured": bool(_environment_key(provider)),
        "fallbackToRule": MODEL_FALLBACK_TO_RULE,
    }


async def complete(
    messages: list[dict[str, str]],
    credential: ModelCredential,
    json_mode: bool = True,
) -> str:
    """Call the configured provider once and return the assistant text."""
    if credential.protocol == "anthropic-messages":
        return await _complete_anthropic(credential, messages)
    return await _complete_openai_compatible(credential, messages, json_mode)


@dataclass
class ModelTurn:
    """One assistant reply, normalised across providers."""

    text: str
    tool_calls: list[ToolCallRecord]


async def call_with_tools(
    system_prompt: str,
    messages: list[AgentMessage],
    tools: list[dict[str, Any]],
    credential: ModelCredential,
) -> ModelTurn:
    """
    Ask the model for its next step, exposing the tool catalog.

    No ``response_format`` is set: providers disagree about whether JSON mode and tool calling can
    be combined, and the loop needs the tool channel to be reliable rather than the text to be
    pre-formatted JSON.
    """
    if credential.protocol == "anthropic-messages":
        return await _turn_anthropic(system_prompt, messages, tools, credential)
    return await _turn_openai_compatible(system_prompt, messages, tools, credential)


async def _turn_openai_compatible(
    system_prompt: str,
    messages: list[AgentMessage],
    tools: list[dict[str, Any]],
    credential: ModelCredential,
) -> ModelTurn:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {credential.api_key}",
    }
    payload: dict[str, Any] = {
        "model": credential.model,
        "messages": to_openai_messages(system_prompt, messages),
        "temperature": credential.temperature,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in tools
        ],
        "tool_choice": "auto",
    }
    response = await _post(credential, headers, payload)
    try:
        message = response.json()["choices"][0]["message"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ModelGatewayError(
            "MODEL_RESPONSE_INVALID",
            "OpenAI-compatible response has no assistant message.",
        ) from exc

    calls: list[ToolCallRecord] = []
    for index, raw in enumerate(message.get("tool_calls") or []):
        function = raw.get("function") or {}
        arguments, parse_error = _parse_tool_arguments(function.get("arguments"))
        calls.append(
            ToolCallRecord(
                call_id=str(raw.get("id") or f"call_{index}"),
                name=str(function.get("name") or ""),
                arguments=arguments,
                parse_error=parse_error,
            )
        )
    return ModelTurn(text=message.get("content") or "", tool_calls=calls)


async def _turn_anthropic(
    system_prompt: str,
    messages: list[AgentMessage],
    tools: list[dict[str, Any]],
    credential: ModelCredential,
) -> ModelTurn:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": credential.api_key,
        "anthropic-version": "2023-06-01",
    }
    payload: dict[str, Any] = {
        "model": credential.model,
        "max_tokens": 2048,
        "temperature": credential.temperature,
        "system": system_prompt,
        "messages": to_anthropic_messages(messages),
        "tools": [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["parameters"],
            }
            for tool in tools
        ],
    }
    response = await _post(credential, headers, payload)
    try:
        blocks = response.json()["content"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ModelGatewayError(
            "MODEL_RESPONSE_INVALID",
            "Anthropic response has no content blocks.",
        ) from exc

    text_parts: list[str] = []
    calls: list[ToolCallRecord] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text_parts.append(str(block.get("text") or ""))
        elif block.get("type") == "tool_use":
            arguments = block.get("input")
            if isinstance(arguments, dict):
                calls.append(
                    ToolCallRecord(
                        call_id=str(block.get("id") or f"call_{index}"),
                        name=str(block.get("name") or ""),
                        arguments=arguments,
                    )
                )
            else:
                calls.append(
                    ToolCallRecord(
                        call_id=str(block.get("id") or f"call_{index}"),
                        name=str(block.get("name") or ""),
                        parse_error="Tool input was not a JSON object.",
                    )
                )
    return ModelTurn(text="".join(text_parts), tool_calls=calls)


def _parse_tool_arguments(raw: Any) -> tuple[dict[str, Any], str | None]:
    if raw is None or raw == "":
        return {}, None
    if isinstance(raw, dict):
        return raw, None
    if not isinstance(raw, str):
        return {}, f"Tool arguments had unexpected type {type(raw).__name__}."
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"Tool arguments were not valid JSON ({exc.msg})."
    if not isinstance(parsed, dict):
        return {}, "Tool arguments were not a JSON object."
    return parsed, None


@dataclass
class ModelStreamEvent:
    """One increment of a streamed model reply."""

    kind: str  # "text" (a delta of prose) or "tool_calls" (the final, complete call list)
    text: str = ""
    tool_calls: list[ToolCallRecord] | None = None


async def stream_call_with_tools(
    system_prompt: str,
    messages: list[AgentMessage],
    tools: list[dict[str, Any]],
    credential: ModelCredential,
) -> AsyncIterator[ModelStreamEvent]:
    """
    Stream the model's next step, yielding text deltas as they arrive and one final tool_calls
    event. This is what makes the assistant's prose appear character by character in the UI.
    """
    if credential.protocol == "anthropic-messages":
        async for event in _stream_turn_anthropic(system_prompt, messages, tools, credential):
            yield event
    else:
        async for event in _stream_turn_openai(system_prompt, messages, tools, credential):
            yield event


async def _stream_turn_openai(
    system_prompt: str,
    messages: list[AgentMessage],
    tools: list[dict[str, Any]],
    credential: ModelCredential,
) -> AsyncIterator[ModelStreamEvent]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {credential.api_key}",
    }
    payload: dict[str, Any] = {
        "model": credential.model,
        "messages": to_openai_messages(system_prompt, messages),
        "temperature": credential.temperature,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in tools
        ],
        "tool_choice": "auto",
        "stream": True,
    }
    tool_slots: dict[int, dict[str, str]] = {}
    async with httpx.AsyncClient(timeout=credential.timeout_seconds) as client:
        async with client.stream("POST", credential.endpoint, headers=headers, json=payload) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", "replace")[:300]
                if credential.api_key:
                    body = body.replace(credential.api_key, "***")
                raise ModelGatewayError("MODEL_REQUEST_FAILED", f"{response.status_code}: {body}")
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    yield ModelStreamEvent("text", text=content)
                for raw in delta.get("tool_calls") or []:
                    index = int(raw.get("index", 0))
                    slot = tool_slots.setdefault(index, {"id": "", "name": "", "arguments": ""})
                    if raw.get("id"):
                        slot["id"] = raw["id"]
                    function = raw.get("function") or {}
                    if function.get("name"):
                        slot["name"] += function["name"]
                    if function.get("arguments"):
                        slot["arguments"] += function["arguments"]
    calls = [
        ToolCallRecord(
            call_id=slot["id"] or f"call_{index}",
            name=slot["name"],
            arguments=_parse_tool_arguments(slot["arguments"])[0],
            parse_error=_parse_tool_arguments(slot["arguments"])[1],
        )
        for index, slot in sorted(tool_slots.items())
    ]
    if calls:
        yield ModelStreamEvent("tool_calls", tool_calls=calls)


async def _stream_turn_anthropic(
    system_prompt: str,
    messages: list[AgentMessage],
    tools: list[dict[str, Any]],
    credential: ModelCredential,
) -> AsyncIterator[ModelStreamEvent]:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": credential.api_key,
        "anthropic-version": "2023-06-01",
    }
    payload: dict[str, Any] = {
        "model": credential.model,
        "max_tokens": 2048,
        "temperature": credential.temperature,
        "system": system_prompt,
        "messages": to_anthropic_messages(messages),
        "tools": [
            {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["parameters"],
            }
            for tool in tools
        ],
        "stream": True,
    }
    tool_ids: dict[int, str] = {}
    tool_names: dict[int, str] = {}
    tool_inputs: dict[int, str] = {}
    async with httpx.AsyncClient(timeout=credential.timeout_seconds) as client:
        async with client.stream("POST", credential.endpoint, headers=headers, json=payload) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", "replace")[:300]
                if credential.api_key:
                    body = body.replace(credential.api_key, "***")
                raise ModelGatewayError("MODEL_REQUEST_FAILED", f"{response.status_code}: {body}")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type == "content_block_start":
                    block = event.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        index = int(event.get("index", 0))
                        tool_ids[index] = block.get("id")
                        tool_names[index] = block.get("name")
                elif event_type == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        yield ModelStreamEvent("text", text=delta.get("text") or "")
                    elif delta.get("type") == "input_json_delta":
                        index = int(event.get("index", 0))
                        tool_inputs[index] = tool_inputs.get(index, "") + (delta.get("partial_json") or "")
                elif event_type == "message_stop":
                    break
    calls = []
    for index in sorted(tool_inputs):
        arguments, parse_error = _parse_tool_arguments(tool_inputs[index])
        calls.append(
            ToolCallRecord(
                call_id=tool_ids.get(index, f"call_{index}"),
                name=tool_names.get(index, ""),
                arguments=arguments,
                parse_error=parse_error,
            )
        )
    if calls:
        yield ModelStreamEvent("tool_calls", tool_calls=calls)


async def probe(credential: ModelCredential) -> dict[str, Any]:
    """
    Minimal round trip used by the "test connection" control. Uses plain text mode so a provider
    that rejects response_format still answers.
    """
    reply = await complete(
        [
            {"role": "system", "content": "You are a connectivity probe. Reply with the single word OK."},
            {"role": "user", "content": "Connection test from FusionPilot."},
        ],
        credential,
        json_mode=False,
    )
    return {
        "provider": credential.provider,
        "label": credential.label,
        "model": credential.model,
        "reply": reply.strip()[:200],
    }


async def _complete_openai_compatible(
    credential: ModelCredential,
    messages: list[dict[str, str]],
    json_mode: bool,
) -> str:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {credential.api_key}",
    }
    payload: dict[str, Any] = {
        "model": credential.model,
        "messages": messages,
        "temperature": credential.temperature,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    response = await _post(credential, headers, payload)
    try:
        return response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ModelGatewayError(
            "MODEL_RESPONSE_INVALID",
            "OpenAI-compatible response has no message content.",
        ) from exc


async def _complete_anthropic(
    credential: ModelCredential,
    messages: list[dict[str, str]],
) -> str:
    system_messages = [message["content"] for message in messages if message["role"] == "system"]
    conversation = [message for message in messages if message["role"] != "system"]
    headers = {
        "Content-Type": "application/json",
        "x-api-key": credential.api_key,
        "anthropic-version": "2023-06-01",
    }
    payload: dict[str, Any] = {
        "model": credential.model,
        "max_tokens": 2048,
        "temperature": credential.temperature,
        "messages": conversation,
    }
    if system_messages:
        payload["system"] = "\n\n".join(system_messages)

    response = await _post(credential, headers, payload)
    try:
        return response.json()["content"][0]["text"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ModelGatewayError(
            "MODEL_RESPONSE_INVALID",
            "Anthropic response has no text content.",
        ) from exc


async def _post(
    credential: ModelCredential,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=credential.timeout_seconds) as client:
            response = await client.post(credential.endpoint, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise ModelGatewayError("MODEL_UNAVAILABLE", str(exc)) from exc
    if response.status_code >= 400:
        # Provider error bodies are forwarded to the UI, so make sure a reflected credential can
        # never ride along with them.
        detail = response.text[:300]
        if credential.api_key:
            detail = detail.replace(credential.api_key, "***")
        raise ModelGatewayError(
            "MODEL_REQUEST_FAILED",
            f"{response.status_code}: {detail}",
        )
    return response
