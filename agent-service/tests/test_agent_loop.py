from fastapi.testclient import TestClient

from app.main import app
from app.agent_service import analyze_result
from app.models import ExperimentPlan, PlanRequest
from app.trace import AgentTraceStore
from app.tools import list_tool_definitions


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
    trace = store.create(request, plan)
    event = store.append(trace.trace_id, "test_event", {"ok": True})
    assert store.get(trace.trace_id).events[0].event_id == event.event_id


def test_execute_requires_confirmation(monkeypatch):
    async def fake_default_config():
        return {"targetCount": 1, "simulationSteps": 1}

    monkeypatch.setattr("app.agent_service.get_default_config", fake_default_config)
    client = TestClient(app)
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