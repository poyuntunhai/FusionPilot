import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.auth import require_agent_user
from app.main import app
from app.model_gateway import ModelGatewayError, complete, resolve_credential
from app.model_planner import build_plan_with_model
from app.models import PlanRequest
from app.result_analysis import analyze_with_model, extract_metrics


def set_authenticated_user(user_id: int = 1) -> None:
    app.dependency_overrides[require_agent_user] = lambda: {
        "authorization": "Bearer test-token",
        "user": {"userId": user_id},
        "user_id": user_id,
    }


def plan_json(**overrides) -> str:
    payload = {
        "title": "model plan",
        "goal": "goal",
        "assumptions": [],
        "experiment_config": {"targetCount": 2},
        "baselines": ["ROUND_ROBIN"],
        "metrics": ["trackingRate"],
        "execution_steps": ["run it"],
        "expected_outputs": ["metrics"],
        "requires_confirmation": True,
        "recommended_tool": "run_simulation",
    }
    payload.update(overrides)
    return json.dumps(payload)


# --------------------------------------------------------------------------- credential resolution


def test_request_key_wins_over_the_server_key(monkeypatch):
    monkeypatch.setattr("app.model_gateway.MODEL_PROVIDER", "openai")
    monkeypatch.setattr("app.model_gateway.MODEL_API_KEY", "server-key")

    credential = resolve_credential("openai", "gpt-4o-mini", "user-key")

    assert credential.api_key == "user-key"


def test_server_key_only_applies_to_its_own_provider(monkeypatch):
    monkeypatch.setattr("app.model_gateway.MODEL_PROVIDER", "openai")
    monkeypatch.setattr("app.model_gateway.MODEL_API_KEY", "server-key")

    # The server key must not silently be sent to a different provider.
    with pytest.raises(ModelGatewayError) as error:
        resolve_credential("deepseek", None, None)
    assert error.value.code == "MODEL_API_KEY_MISSING"

    assert resolve_credential("openai").api_key == "server-key"


def test_missing_key_is_reported_rather_than_guessed(monkeypatch):
    monkeypatch.setattr("app.model_gateway.MODEL_PROVIDER", "rule")
    monkeypatch.setattr("app.model_gateway.MODEL_API_KEY", "")

    with pytest.raises(ModelGatewayError) as error:
        resolve_credential("qwen", None, None)

    assert error.value.code == "MODEL_API_KEY_MISSING"


# --------------------------------------------------------------------------- key never persists


def test_api_key_never_reaches_a_persisted_trace(monkeypatch):
    captured: dict = {}

    async def fake_default_config():
        return {"targetCount": 1, "simulationSteps": 1}

    async def fake_complete(messages, credential, json_mode=True):
        return plan_json()

    async def fake_persist_trace(trace, authorization):
        captured["trace"] = json.dumps(trace, ensure_ascii=False)

    monkeypatch.setattr("app.agent_service.get_default_config", fake_default_config)
    monkeypatch.setattr("app.model_planner.complete", fake_complete)
    monkeypatch.setattr("app.main.save_agent_trace", fake_persist_trace)
    set_authenticated_user()
    client = TestClient(app)
    secret = "sk-super-secret-token-value"
    try:
        response = client.post(
            "/api/v1/agent/sessions",
            json={
                "goal": "Plan an experiment with my own model token",
                "model_provider": "deepseek",
                "model_name": "deepseek-chat",
            },
            headers={"X-Model-Api-Key": secret},
        )

        assert response.status_code == 200
        assert response.json()["plan"]["planner"] == "deepseek"
        # The token must not appear in the response body nor in what gets persisted.
        assert secret not in response.text
        assert secret not in captured["trace"]
    finally:
        app.dependency_overrides.pop(require_agent_user, None)


def test_provider_error_text_never_echoes_the_key(monkeypatch):
    class FakeResponse:
        status_code = 400
        text = "invalid key: user-token"

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr("app.model_gateway.httpx.AsyncClient", FakeClient)
    credential = resolve_credential("openai", None, "user-token")

    with pytest.raises(ModelGatewayError) as error:
        asyncio.run(complete([{"role": "user", "content": "hi"}], credential))

    assert "user-token" not in error.value.message
    assert "***" in error.value.message


# --------------------------------------------------------------------------- model driven planning


def test_user_token_enables_a_provider_the_server_never_configured(monkeypatch):
    captured: dict = {}

    async def fake_complete(messages, credential, json_mode=True):
        captured["provider"] = credential.provider
        captured["api_key"] = credential.api_key
        captured["model"] = credential.model
        return plan_json(recommended_tool="compare_scheduling_policies")

    monkeypatch.setattr("app.model_planner.complete", fake_complete)
    request = PlanRequest(
        goal="Compare scheduling policies using my own token",
        model_provider="deepseek",
        model_name="deepseek-chat",
    )
    credential = resolve_credential("deepseek", "deepseek-chat", "user-token")

    plan = asyncio.run(build_plan_with_model(request, {"targetCount": 2}, credential))

    assert captured == {"provider": "deepseek", "api_key": "user-token", "model": "deepseek-chat"}
    assert plan.planner == "deepseek"
    assert plan.model == "deepseek-chat"
    assert plan.recommended_tool == "compare_scheduling_policies"


def test_model_config_is_merged_onto_the_default(monkeypatch):
    """
    Models routinely return a partial experiment_config. Using it verbatim drops required fields
    and the run then fails validation, so the default must supply the missing keys.
    """
    async def fake_complete(messages, credential, json_mode=True):
        return plan_json(experiment_config={"schedulingPolicy": "PRIORITY"})

    monkeypatch.setattr("app.model_planner.complete", fake_complete)
    default_config = {
        "targetCount": 3,
        "simulationSteps": 100,
        "schedulingPolicy": "ROUND_ROBIN",
        "fusionMethod": "WEIGHTED_AVERAGE",
    }
    request = PlanRequest(
        goal="Run a tracking experiment with a model",
        model_provider="openai",
        target_count=5,
    )
    credential = resolve_credential("openai", "gpt-4o-mini", "user-token")

    plan = asyncio.run(build_plan_with_model(request, default_config, credential))

    # Keys the model omitted survive from the default.
    assert plan.experiment_config["fusionMethod"] == "WEIGHTED_AVERAGE"
    assert plan.experiment_config["simulationSteps"] == 100
    # The model's own choice is applied...
    assert plan.experiment_config["schedulingPolicy"] == "PRIORITY"
    # ...and an explicit request field still wins over the model.
    assert plan.experiment_config["targetCount"] == 5


def test_model_failure_falls_back_with_a_visible_note(monkeypatch):
    async def failing_complete(messages, credential, json_mode=True):
        raise ModelGatewayError("MODEL_UNAVAILABLE", "connection refused")

    monkeypatch.setattr("app.model_planner.complete", failing_complete)
    monkeypatch.setattr("app.model_planner.MODEL_FALLBACK_TO_RULE", True)
    request = PlanRequest(goal="Run a tracking experiment", model_provider="openai")
    credential = resolve_credential("openai", "gpt-4o-mini", "user-token")

    plan = asyncio.run(build_plan_with_model(request, {"targetCount": 1}, credential))

    assert plan.planner == "rule-fallback"
    assert plan.planning_note is not None
    assert "local rule planner" in plan.planning_note


def test_request_for_a_model_without_any_key_is_labelled(monkeypatch):
    monkeypatch.setattr("app.model_gateway.MODEL_PROVIDER", "rule")
    monkeypatch.setattr("app.model_gateway.MODEL_API_KEY", "")

    request = PlanRequest(goal="Compare scheduling policies", model_provider="openai")
    plan = asyncio.run(build_plan_with_model(request, {"targetCount": 1}, None))

    assert plan.planner == "rule-fallback"
    assert plan.model == "openai"
    assert plan.planning_note is not None


# --------------------------------------------------------------------------- model driven analysis


def test_model_analysis_drops_metric_names_it_invented(monkeypatch):
    async def fake_complete(messages, credential, json_mode=True):
        return json.dumps(
            {
                "summary": "Tracking rate is high while resource use stays bounded.",
                "evidence": [
                    {"metric": "trackingRate", "value": 0.5, "note": "high"},
                    {"metric": "imaginaryMetric", "value": 999, "note": "made up"},
                ],
                "limitations": ["single seed"],
            }
        )

    monkeypatch.setattr("app.result_analysis.complete", fake_complete)
    credential = resolve_credential("openai", "gpt-4o-mini", "user-token")

    analysis = asyncio.run(
        analyze_with_model({"metrics": {"trackingRate": 0.8}}, None, credential)
    )

    assert analysis.metrics == {"trackingRate": 0.8}
    assert [item["metric"] for item in analysis.evidence] == ["trackingRate"]
    # The value must be the backend's, not the model's restatement of it.
    assert analysis.evidence[0]["value"] == 0.8
    assert analysis.produced_by == "openai:gpt-4o-mini"
    assert "single seed" in analysis.limitations


def test_analysis_without_a_model_stays_metric_only():
    from app.agent_service import analyze_result

    analysis = analyze_result({"metrics": {"trackingRate": 0.8}})

    assert analysis.metrics == {"trackingRate": 0.8}
    assert analysis.evidence[0]["source"] == "java-backend-result"
    assert analysis.produced_by == "rule"


def test_comparison_results_are_flattened_so_the_model_can_read_them():
    metrics = extract_metrics(
        {
            "roundRobin": {"metrics": {"trackingRate": 0.7, "averagePositionError": 4.0}},
            "priority": {"metrics": {"trackingRate": 0.9, "averagePositionError": 3.1}},
            "priorityMinusRoundRobin": {"trackingRateDelta": 0.2},
        }
    )

    assert metrics == {
        "roundRobin.trackingRate": 0.7,
        "roundRobin.averagePositionError": 4.0,
        "priority.trackingRate": 0.9,
        "priority.averagePositionError": 3.1,
        "delta.trackingRateDelta": 0.2,
    }


# --------------------------------------------------------------------------- connection test route


def test_connection_test_reports_a_rejected_token(monkeypatch):
    async def failing_probe(credential):
        raise ModelGatewayError("MODEL_REQUEST_FAILED", "401: invalid api key")

    monkeypatch.setattr("app.main.probe", failing_probe)
    set_authenticated_user()
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/agent/models/test",
            json={"provider": "openai", "model": "gpt-4o-mini"},
            headers={"X-Model-Api-Key": "bad-token"},
        )

        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "MODEL_REQUEST_FAILED"
    finally:
        app.dependency_overrides.pop(require_agent_user, None)


def test_connection_test_succeeds_with_a_token(monkeypatch):
    async def ok_probe(credential):
        return {
            "provider": credential.provider,
            "label": credential.label,
            "model": credential.model,
            "reply": "OK",
        }

    monkeypatch.setattr("app.main.probe", ok_probe)
    set_authenticated_user()
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/agent/models/test",
            json={"provider": "openai", "model": "gpt-4o-mini"},
            headers={"X-Model-Api-Key": "good-token"},
        )

        assert response.status_code == 200
        assert response.json()["reply"] == "OK"
        assert response.json()["model"] == "gpt-4o-mini"
    finally:
        app.dependency_overrides.pop(require_agent_user, None)


def test_connection_test_without_a_key_asks_for_one(monkeypatch):
    monkeypatch.setattr("app.model_gateway.MODEL_PROVIDER", "rule")
    monkeypatch.setattr("app.model_gateway.MODEL_API_KEY", "")
    set_authenticated_user()
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/agent/models/test",
            json={"provider": "openai"},
        )

        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "MODEL_API_KEY_MISSING"
    finally:
        app.dependency_overrides.pop(require_agent_user, None)


def test_model_catalog_marks_providers_available_when_a_token_is_supplied(monkeypatch):
    monkeypatch.setattr("app.model_gateway.MODEL_PROVIDER", "rule")
    monkeypatch.setattr("app.model_gateway.MODEL_API_KEY", "")
    set_authenticated_user()
    client = TestClient(app)
    try:
        without = client.get("/api/v1/agent/models").json()
        with_token = client.get(
            "/api/v1/agent/models",
            headers={"X-Model-Api-Key": "user-token"},
        ).json()

        assert without["hasRequestKey"] is False
        assert all(item["configured"] is False for item in without["providers"])
        assert with_token["hasRequestKey"] is True
        assert all(item["configured"] is True for item in with_token["providers"])
        # The server-side flag stays separate so the UI can tell the two apart.
        assert all(item["serverConfigured"] is False for item in with_token["providers"])
    finally:
        app.dependency_overrides.pop(require_agent_user, None)
