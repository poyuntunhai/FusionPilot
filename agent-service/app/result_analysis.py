import json
from typing import Any

from .model_gateway import ModelCredential, ModelGatewayError, complete
from .model_planner import parse_json_object
from .models import ExperimentPlan, ResultAnalysis


ANALYST_SYSTEM_PROMPT = """You are the analysis module of FusionPilot, a radar and electronic-countermeasure simulation platform.
You receive structured metrics that the Java simulation core already produced.

Hard rules:
- Use only the numbers present in the supplied metrics object. Never invent, extrapolate, or "recall" a value.
- Never mention a metric name that is not in the supplied metrics object.
- If the supplied metrics cannot support a claim, put that in limitations instead of guessing.
- The Java backend remains the source of truth. You are interpreting its output, not producing results.

Return only valid JSON with this shape:
{"summary": "<2-4 sentences>", "evidence": [{"metric": "<exact metric name>", "value": <number>, "note": "<short reading>"}], "limitations": ["<short string>"]}"""


def extract_metrics(result: dict[str, Any]) -> dict[str, Any]:
    """
    Flatten a Java result into one metrics dictionary.

    Handles both a single run (`metrics`) and a policy comparison, which nests two complete
    results plus a delta block. Without this the comparison case produced an empty analysis.
    """
    if not isinstance(result, dict):
        return {}

    single = result.get("metrics")
    if isinstance(single, dict) and single:
        return dict(single)

    flattened: dict[str, Any] = {}
    for side in ("roundRobin", "priority"):
        block = result.get(side)
        if isinstance(block, dict) and isinstance(block.get("metrics"), dict):
            for key, value in block["metrics"].items():
                flattened[f"{side}.{key}"] = value
    delta = result.get("priorityMinusRoundRobin")
    if isinstance(delta, dict):
        for key, value in delta.items():
            flattened[f"delta.{key}"] = value
    return flattened


def analyze_result(result: dict[str, Any]) -> ResultAnalysis:
    """Deterministic reading of the structured metrics, used when no model is available."""
    metrics = extract_metrics(result)
    evidence = [
        {"metric": key, "value": value, "source": "java-backend-result"}
        for key, value in metrics.items()
    ]
    return ResultAnalysis(
        summary=(
            "Analysis is limited to structured metrics returned by the Java backend."
            if metrics
            else "The tool returned no structured metrics to summarize."
        ),
        metrics=metrics,
        evidence=evidence,
        limitations=[
            "No language model was used, so no interpretation beyond the raw metric values is offered.",
            "No conclusion is inferred when a metric is absent from the structured result.",
        ],
        produced_by="rule",
    )


async def analyze_with_model(
    result: dict[str, Any],
    plan: ExperimentPlan | None,
    credential: ModelCredential,
) -> ResultAnalysis:
    """
    Ask the selected model to interpret the structured metrics.

    The model is never trusted for numbers: the returned metrics come from the Java result, the
    model only contributes the reading. Evidence rows naming an unknown metric are dropped, so a
    hallucinated metric name cannot reach the UI.
    """
    metrics = extract_metrics(result)
    if not metrics:
        fallback = analyze_result(result)
        return fallback.model_copy(
            update={
                "produced_by": f"{credential.provider}:{credential.model}",
                "limitations": fallback.limitations
                + ["The tool returned no structured metrics, so the model had nothing to interpret."],
            }
        )

    messages = [
        {"role": "system", "content": ANALYST_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "research_goal": plan.goal if plan else None,
                    "plan_title": plan.title if plan else None,
                    "plan_assumptions": plan.assumptions if plan else [],
                    "metrics": metrics,
                },
                ensure_ascii=False,
            ),
        },
    ]
    content = await complete(messages, credential)
    parsed = parse_json_object(content)

    allowed = set(metrics)
    evidence: list[dict[str, Any]] = []
    for item in parsed.get("evidence", []) or []:
        if not isinstance(item, dict):
            continue
        name = item.get("metric")
        if name not in allowed:
            # Drop anything the model invented rather than echoing an unverifiable claim.
            continue
        evidence.append(
            {
                "metric": name,
                # Always the backend value, never the model's restatement of it.
                "value": metrics[name],
                "note": str(item.get("note", ""))[:300],
                "source": "java-backend-result",
            }
        )

    summary = str(parsed.get("summary", "")).strip()
    if not summary:
        summary = "The model returned no summary; only the structured metrics are shown."

    raw_limitations = parsed.get("limitations", []) or []
    limitations = [str(item)[:300] for item in raw_limitations if str(item).strip()]
    limitations.append(
        "Interpretation was generated by a language model from the structured metrics; "
        "simulation values themselves come from the Java backend."
    )

    return ResultAnalysis(
        summary=summary[:1200],
        metrics=metrics,
        evidence=evidence,
        limitations=limitations,
        produced_by=f"{credential.provider}:{credential.model}",
    )


def describe_failure(error: ModelGatewayError) -> str:
    """Turn a gateway failure into a short, user-facing reason."""
    if error.code == "MODEL_API_KEY_MISSING":
        return "No API key was supplied for the selected provider."
    if error.code == "MODEL_PROVIDER_UNSUPPORTED":
        return error.message
    return error.message
