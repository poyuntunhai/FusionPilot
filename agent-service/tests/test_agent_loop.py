from fastapi.testclient import TestClient

from app.main import app
from app.agent_service import analyze_result
from app.auth import require_agent_user
from app.models import ExperimentPlan, PlanRequest
from app.trace import AgentTraceStore
from app.tools import list_tool_definitions


def set_authenticated_user(user_id: int = 1) -> None:
    app.dependency_overrides[require_agent_user] = lambda: {
        "authorization": "Bearer test-token",
        "user": {"userId": user_id},
        "user_id": user_id,
    }


async def fake_persist_trace(trace: dict, authorization: str) -> None:
    return None


def test_tool_registry_contains_core_tools():
    names = {tool.name for tool in list_tool_definitions()}
    assert names == {
        "validate_experiment",
        "run_simulation",
        "calculate_metrics",
        "compare_scheduling_policies",
    }


def test_analysis_only_uses_returned_metrics():
    analysis = analyze_result({"metrics": {"trackingRate": 0.8}})
    assert analysis.metrics == {"trackingRate": 0.8}
    assert analysis.evidence[0]["source"] == "java-backend-result"


def test_trace_store_persists_events():
    store = AgentTraceStore()
    request = PlanRequest(goal="Run a reproducible tracking experiment")
    plan = ExperimentPlan(
        title="test",
        goal=request.goal,
        assumptions=[],
        experiment_config={},
        baselines=[],
        metrics=[],
        execution_steps=[],
        expected_outputs=[],
    )
    trace = store.create(request, plan, owner_user_id=1)
    event = store.append(trace.trace_id, "test_event", {"ok": True})
    assert store.get(trace.trace_id).events[0].event_id == event.event_id


def test_execute_requires_confirmation(monkeypatch):
    async def fake_default_config():
        return {"targetCount": 1, "simulationSteps": 1}

    monkeypatch.setattr("app.agent_service.get_default_config", fake_default_config)
    monkeypatch.setattr("app.main.save_agent_trace", fake_persist_trace)
    set_authenticated_user()
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/agent/sessions",
            json={"goal": "Run a reproducible tracking experiment"},
        )
        assert response.status_code == 200
        trace_id = response.json()["trace_id"]
        response = client.post(
            f"/api/v1/agent/sessions/{trace_id}/execute",
            json={"tool_name": "run_simulation"},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "CONFIRMATION_REQUIRED"
    finally:
        app.dependency_overrides.pop(require_agent_user, None)


def test_session_uses_model_planner_boundary(monkeypatch):
    async def fake_default_config():
        return {"targetCount": 1, "simulationSteps": 1}

    async def fake_model_plan(request, default_config):
        return ExperimentPlan(
            title="model-planned",
            goal=request.goal,
            assumptions=[],
            experiment_config=default_config,
            baselines=["ROUND_ROBIN"],
            metrics=[],
            execution_steps=[],
            expected_outputs=[],
            planner="test-model",
            model="test-model-v1",
        )

    monkeypatch.setattr("app.agent_service.get_default_config", fake_default_config)
    monkeypatch.setattr("app.agent_service.build_plan_with_model", fake_model_plan)
    monkeypatch.setattr("app.main.save_agent_trace", fake_persist_trace)
    set_authenticated_user()
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/agent/sessions",
            json={"goal": "Use the model planner for this experiment"},
        )
        assert response.status_code == 200
        assert response.json()["plan"]["planner"] == "test-model"
    finally:
        app.dependency_overrides.pop(require_agent_user, None)


def test_agent_routes_require_authentication():
    app.dependency_overrides.pop(require_agent_user, None)
    client = TestClient(app)

    response = client.post(
        "/api/v1/agent/sessions",
        json={"goal": "Run a reproducible tracking experiment"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "UNAUTHORIZED"


def test_trace_is_hidden_from_other_users(monkeypatch):
    async def fake_default_config():
        return {"targetCount": 1, "simulationSteps": 1}

    monkeypatch.setattr("app.agent_service.get_default_config", fake_default_config)
    monkeypatch.setattr("app.main.save_agent_trace", fake_persist_trace)
    set_authenticated_user(user_id=1)
    client = TestClient(app)
    try:
        response = client.post(
            "/api/v1/agent/sessions",
            json={"goal": "Create a trace for ownership testing"},
        )
        assert response.status_code == 200
        trace_id = response.json()["trace_id"]

        set_authenticated_user(user_id=2)
        response = client.get(f"/api/v1/agent/sessions/{trace_id}")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "TRACE_NOT_FOUND"
    finally:
        app.dependency_overrides.pop(require_agent_user, None)
