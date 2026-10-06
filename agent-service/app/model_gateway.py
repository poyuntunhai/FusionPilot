from dataclasses import dataclass
from typing import Any

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


PROVIDER_PRESETS = {
    "openai": ProviderPreset(
        "openai",
        "OpenAI",
        "openai-compatible",
        "https://api.openai.com/v1/chat/completions",
        "gpt-4o-mini",
        ("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"),
    ),
    "anthropic": ProviderPreset(
        "anthropic",
        "Claude",
        "anthropic-messages",
        "https://api.anthropic.com/v1/messages",
        "claude-3-5-haiku-latest",
        ("claude-3-5-haiku-latest", "claude-3-5-sonnet-latest", "claude-3-7-sonnet-latest"),
    ),
    "deepseek": ProviderPreset(
        "deepseek",
        "DeepSeek",
        "openai-compatible",
        "https://api.deepseek.com/chat/completions",
        "deepseek-chat",
        ("deepseek-chat", "deepseek-reasoner"),
    ),
    "qwen": ProviderPreset(
        "qwen",
        "Qwen",
        "openai-compatible",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "qwen-plus",
        ("qwen-plus", "qwen-turbo", "qwen-max", "qwen-long"),
    ),
    "zhipu": ProviderPreset(
        "zhipu",
        "Zhipu",
        "openai-compatible",
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "glm-4-flash",
        ("glm-4-flash", "glm-4-plus", "glm-4-air"),
    ),
}


def provider_catalog() -> list[dict[str, Any]]:
    return [
        {
            "provider": preset.provider,
            "label": preset.label,
            "protocol": preset.protocol,
            "defaultModel": preset.default_model,
            "modelOptions": list(preset.model_options),
            "configured": preset.provider == MODEL_PROVIDER and bool(MODEL_API_KEY),
        }
        for preset in PROVIDER_PRESETS.values()
    ]


def current_provider(
    provider_name: str | None = None,
    model_name: str | None = None,
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
            "fallbackToRule": MODEL_FALLBACK_TO_RULE,
        }
    preset = PROVIDER_PRESETS.get(provider)
    if preset is None:
        raise ModelGatewayError("MODEL_PROVIDER_UNSUPPORTED", f"Unsupported model provider: {provider}")
    return {
        "provider": preset.provider,
        "label": preset.label,
        "protocol": preset.protocol,
        "model": requested_model or MODEL_NAME or preset.default_model,
        "configured": provider == MODEL_PROVIDER and bool(MODEL_API_KEY),
        "fallbackToRule": MODEL_FALLBACK_TO_RULE,
    }


async def complete(
    messages: list[dict[str, str]],
    provider_name: str | None = None,
    model_name: str | None = None,
) -> str:
    provider = (provider_name or MODEL_PROVIDER or "rule").strip().lower()
    requested_model = (model_name or "").strip()
    preset = PROVIDER_PRESETS.get(provider)
    if provider == "rule":
        raise ModelGatewayError("MODEL_DISABLED", "Rule-based mode does not call an external model.")
    if preset is None:
        raise ModelGatewayError("MODEL_PROVIDER_UNSUPPORTED", f"Unsupported model provider: {provider}")
    if provider != MODEL_PROVIDER or not MODEL_API_KEY:
        raise ModelGatewayError("MODEL_API_KEY_MISSING", f"API key is missing for provider: {provider}")

    endpoint = MODEL_API_BASE_URL or preset.endpoint
    headers = {"Content-Type": "application/json"}
    if preset.protocol == "anthropic-messages":
        return await _complete_anthropic(endpoint, headers, messages, preset, requested_model)

    headers["Authorization"] = f"Bearer {MODEL_API_KEY}"
    payload = {
        "model": requested_model or MODEL_NAME or preset.default_model,
        "messages": messages,
        "temperature": MODEL_TEMPERATURE,
        "response_format": {"type": "json_object"},
    }
    try:
        async with httpx.AsyncClient(timeout=MODEL_TIMEOUT_SECONDS) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise ModelGatewayError("MODEL_UNAVAILABLE", str(exc)) from exc
    if response.status_code >= 400:
        raise ModelGatewayError("MODEL_REQUEST_FAILED", f"{response.status_code}: {response.text[:300]}")
    try:
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ModelGatewayError("MODEL_RESPONSE_INVALID", "OpenAI-compatible response has no message content.") from exc


async def _complete_anthropic(
    endpoint: str,
    headers: dict[str, str],
    messages: list[dict[str, str]],
    preset: ProviderPreset,
    requested_model: str = "",
) -> str:
    system_messages = [message["content"] for message in messages if message["role"] == "system"]
    conversation = [message for message in messages if message["role"] != "system"]
    headers.update(
        {
            "x-api-key": MODEL_API_KEY,
            "anthropic-version": "2023-06-01",
        }
    )
    payload = {
        "model": requested_model or MODEL_NAME or preset.default_model,
        "max_tokens": 2048,
        "temperature": MODEL_TEMPERATURE,
        "messages": conversation,
    }
    if system_messages:
        payload["system"] = "\n\n".join(system_messages)
    try:
        async with httpx.AsyncClient(timeout=MODEL_TIMEOUT_SECONDS) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise ModelGatewayError("MODEL_UNAVAILABLE", str(exc)) from exc
    if response.status_code >= 400:
        raise ModelGatewayError("MODEL_REQUEST_FAILED", f"{response.status_code}: {response.text[:300]}")
    try:
        data = response.json()
        return data["content"][0]["text"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ModelGatewayError("MODEL_RESPONSE_INVALID", "Anthropic response has no text content.") from exc
