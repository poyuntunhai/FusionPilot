from app.model_gateway import current_provider, provider_catalog
from app.model_planner import parse_json_object


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


def test_parse_json_object_accepts_markdown_fenced_model_output():
    result = parse_json_object('```json\n{"title": "demo", "metrics": []}\n```')

    assert result["title"] == "demo"
    assert result["metrics"] == []
