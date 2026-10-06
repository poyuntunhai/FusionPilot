import json
import re
from typing import Any

from .model_gateway import ModelGatewayError, complete, current_provider
from .models import ExperimentPlan, PlanRequest
from .rules import build_plan


SYSTEM_PROMPT = """You are the planning model for FusionPilot, an integrated radar and electronic-countermeasure simulation platform.
Return only valid JSON. Do not invent simulation facts. Use the supplied default configuration and preserve its field names.
The JSON must contain: title, goal, assumptions, experiment_config, baselines, metrics, execution_steps, expected_outputs, requires_confirmation.
The Java backend is the source of truth for all simulation results. The plan may propose experiments, but it must not claim results."""


async def build_plan_with_model(request: PlanRequest, default_config: dict[str, Any]) -> ExperimentPlan:
    fallback = build_plan(request, default_config)
    provider = current_provider(request.model_provider, request.model_name)
    if provider["provider"] == "rule":
        return fallback

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "goal": request.goal,
                    "target_count": request.target_count,
                    "simulation_steps": request.simulation_steps,
                    "scheduling_policy": request.scheduling_policy,
                    "compare_policies": request.compare_policies,
                    "default_config": default_config,
                },
                ensure_ascii=False,
            ),
        },
    ]
    try:
        content = await complete(messages, request.model_provider, request.model_name)
        plan = ExperimentPlan.model_validate(parse_json_object(content))
        return plan.model_copy(
            update={
                "goal": request.goal,
                "requires_confirmation": True,
                "planner": provider["provider"],
                "model": provider["model"],
            }
        )
    except (ModelGatewayError, json.JSONDecodeError, ValueError):
        if provider["fallbackToRule"]:
            return fallback.model_copy(
                update={
                    "planner": "rule-fallback",
                    "model": f"{provider['provider']}:{provider['model']}",
                }
            )
        raise


def parse_json_object(content: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else content.strip()
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise json.JSONDecodeError("No JSON object found", candidate, 0)
        candidate = candidate[start : end + 1]
    value = json.loads(candidate)
    if not isinstance(value, dict):
        raise json.JSONDecodeError("Expected JSON object", candidate, 0)
    return value
