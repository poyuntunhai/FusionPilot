import json
import re
from typing import Any

from .config import MODEL_FALLBACK_TO_RULE
from .model_gateway import ModelCredential, ModelGatewayError, complete
from .models import ExperimentPlan, PlanRequest
from .rules import build_plan


SYSTEM_PROMPT = """You are the planning model for FusionPilot, an integrated radar and electronic-countermeasure simulation platform.
Return only valid JSON. Do not invent simulation facts. Use the supplied default configuration and preserve its field names.
The JSON must contain: title, goal, assumptions, experiment_config, baselines, metrics, execution_steps, expected_outputs, requires_confirmation, recommended_tool.
recommended_tool must be exactly one of: validate_experiment, run_simulation, calculate_metrics, compare_scheduling_policies.
The Java backend is the source of truth for all simulation results. The plan may propose experiments, but it must not claim results or invent metric values."""


async def build_plan_with_model(
    request: PlanRequest,
    default_config: dict[str, Any],
    credential: ModelCredential | None = None,
) -> ExperimentPlan:
    """
    Build the experiment plan, using the selected model when a credential is available.

    `credential` is resolved by the caller from the request plus the optional `X-Model-Api-Key`
    header. When it is absent the local rule planner answers, either directly (when the caller
    asked for rule mode) or as a clearly labelled fallback (when they asked for a model but no key
    was available).
    """
    fallback = build_plan(request, default_config)
    requested_provider = (request.model_provider or "").strip().lower()

    if credential is None:
        if requested_provider and requested_provider != "rule":
            return _rule_fallback(
                fallback,
                requested_provider,
                request.model_name,
                "No API key is available for the selected provider.",
            )
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
        content = await complete(messages, credential)
        plan = ExperimentPlan.model_validate(parse_json_object(content))
        return plan.model_copy(
            update={
                "goal": request.goal,
                "requires_confirmation": True,
                "planner": credential.provider,
                "model": credential.model,
                # A language model routinely returns a partial config. Using it verbatim would
                # drop required fields and make the run fail validation, so the model only gets
                # to override keys on top of the known-good default.
                "experiment_config": merge_experiment_config(
                    default_config,
                    plan.experiment_config,
                    request,
                ),
            }
        )
    except (ModelGatewayError, json.JSONDecodeError, ValueError) as exc:
        if MODEL_FALLBACK_TO_RULE:
            return _rule_fallback(
                fallback,
                credential.provider,
                credential.model,
                f"The model call failed ({exc}).",
            )
        raise


def merge_experiment_config(
    default_config: dict[str, Any],
    model_config: dict[str, Any] | None,
    request: PlanRequest,
) -> dict[str, Any]:
    """
    Layer the model's proposal onto the default configuration.

    Precedence, lowest to highest: backend default -> model proposal -> explicit request fields.
    The default supplies every required key, the model contributes the experiment it designed,
    and anything the user typed into the workbench wins over both.
    """
    merged = dict(default_config)
    if isinstance(model_config, dict):
        for key, value in model_config.items():
            if value is not None:
                merged[key] = value
    if request.target_count is not None:
        merged["targetCount"] = request.target_count
    if request.simulation_steps is not None:
        merged["simulationSteps"] = request.simulation_steps
    if request.scheduling_policy is not None:
        merged["schedulingPolicy"] = request.scheduling_policy
    return merged


def _rule_fallback(
    fallback: ExperimentPlan,
    provider: str,
    model: str | None,
    reason: str,
) -> ExperimentPlan:
    model_label = f"{provider}:{model}" if model else provider
    return fallback.model_copy(
        update={
            "planner": "rule-fallback",
            "model": model_label,
            "planning_note": f"{reason} This plan was produced by the local rule planner, not by a language model.",
        }
    )


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
