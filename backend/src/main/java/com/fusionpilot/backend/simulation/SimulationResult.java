package com.fusionpilot.backend.simulation;

import com.fusionpilot.backend.scenario.ExperimentConfig;

import java.time.Instant;
import java.util.List;

public record SimulationResult(
        String runId,
        ExperimentConfig config,
        List<SimulationStepResult> steps,
        AggregateMetrics metrics,
        Instant completedAt
) {
}