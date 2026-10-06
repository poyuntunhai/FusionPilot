import asyncio

from app.model_gateway import current_provider, provider_catalog
from app.model_planner import build_plan_with_model, parse_json_object
from app.models import PlanRequest


def test_rule_provider_is_available_without_external_credentials():
    provider = current_provider()

    assert provider["provider"] == "rule"
    assert provider["configured"] is True
    assert {item["provider"] for item in provider_catalog()} == {
        "openai",
        "anthropic",
        "deepseek",
        "qwen",
        "zhipu",
    }
    assert all(item["defaultModel"] in item["modelOptions"] for item in provider_catalog())


def test_parse_json_object_accepts_markdown_fenced_model_output():
    result = parse_json_object('```json\n{"title": "demo", "metrics": []}\n```')

    assert result["title"] == "demo"
    assert result["metrics"] == []


def test_requested_unconfigured_provider_falls_back_to_rule_plan():
    request = PlanRequest(
        goal="Compare radar scheduling policies with a selected model",
        model_provider="openai",
        model_name="gpt-test",
    )

    plan = asyncio.run(build_plan_with_model(request, {"targetCount": 1, "simulationSteps": 1}))

    assert plan.planner == "rule-fallback"
    assert plan.model == "openai:gpt-test"
