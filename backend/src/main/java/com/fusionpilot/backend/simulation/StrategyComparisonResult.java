package com.fusionpilot.backend.simulation;

public record StrategyComparisonResult(
        SimulationResult roundRobin,
        SimulationResult priority,
        MetricDelta priorityMinusRoundRobin
) {
}