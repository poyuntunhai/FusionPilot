from app.models import PlanRequest
from app.rules import build_plan


def test_build_plan_overrides_default_values():
    default_config = {
        "targetCount": 3,
        "simulationSteps": 100,
        "schedulingPolicy": "ROUND_ROBIN",
    }
    plan = build_plan(
        PlanRequest(
            goal="Compare scheduling strategies in a noisy multi-target scene",
            target_count=5,
            simulation_steps=20,
            compare_policies=True,
        ),
        default_config,
    )

    assert plan.experiment_config["targetCount"] == 5
    assert plan.experiment_config["simulationSteps"] == 20
    assert plan.baselines == ["ROUND_ROBIN", "PRIORITY"]
    assert plan.requires_confirmation is True


def test_build_plan_keeps_default_policy_without_override():
    plan = build_plan(
        PlanRequest(goal="Run a reproducible tracking experiment"),
        {"schedulingPolicy": "ROUND_ROBIN"},
    )

    assert plan.experiment_config["schedulingPolicy"] == "ROUND_ROBIN"
    assert plan.baselines == ["ROUND_ROBIN"]