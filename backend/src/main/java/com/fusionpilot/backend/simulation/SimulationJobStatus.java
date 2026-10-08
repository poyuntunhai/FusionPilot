package com.fusionpilot.backend.simulation;

public record SimulationJobStatus(
        String jobId,
        String status,
        int progressPercent,
        int completedSteps,
        int totalSteps,
        String message,
        String runId,
        SimulationResult result
) {
}
