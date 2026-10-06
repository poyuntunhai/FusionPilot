from .models import ExperimentPlan, PlanRequest


def build_plan(request: PlanRequest, default_config: dict) -> ExperimentPlan:
    config = dict(default_config)
    if request.target_count is not None:
        config["targetCount"] = request.target_count
    if request.simulation_steps is not None:
        config["simulationSteps"] = request.simulation_steps
    if request.scheduling_policy is not None:
        config["schedulingPolicy"] = request.scheduling_policy

    compare = request.compare_policies or _mentions_comparison(request.goal)
    baselines = ["ROUND_ROBIN"]
    if compare:
        baselines.append("PRIORITY")

    return ExperimentPlan(
        title="Multi-source tracking and resource scheduling experiment",
        goal=request.goal,
        assumptions=[
            "The scene is a two-dimensional discrete-time synthetic environment.",
            "Radar, EO/IR, and prior-knowledge sources provide noisy observations.",
            "The Java backend remains the source of truth for simulation data.",
        ],
        experiment_config=config,
        baselines=baselines,
        metrics=[
            "averagePositionError",
            "trackingRate",
            "resourceUtilization",
            "averageWaitingTime",
            "schedulingSwitches",
        ],
        execution_steps=[
            "Validate the structured experiment configuration.",
            "Run the Java simulation after user confirmation.",
            "Collect structured trajectory, fusion, scheduling, and metric results.",
            "Compare scheduling policies when comparison is requested.",
            "Explain findings using only returned metrics and stated assumptions.",
        ],
        expected_outputs=[
            "A reproducible simulation result with a fixed random seed.",
            "Time-series true states, observations, fused states, and scheduling decisions.",
            "Metric summary suitable for visualization and research notes.",
        ],
        requires_confirmation=True,
    )


def _mentions_comparison(goal: str) -> bool:
    keywords = ("compare", "comparison", "policy", "strategy", "\u5bf9\u6bd4", "\u7b56\u7565")
    normalized = goal.lower()
    return any(keyword in normalized for keyword in keywords)