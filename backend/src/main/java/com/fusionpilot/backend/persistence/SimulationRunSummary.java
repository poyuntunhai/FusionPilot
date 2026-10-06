package com.fusionpilot.backend.persistence;

import java.time.Instant;

public record SimulationRunSummary(
        String runId,
        String scenarioName,
        int targetCount,
        int simulationSteps,
        String schedulingPolicy,
        long randomSeed,
        double averagePositionError,
        double trackingRate,
        double resourceUtilization,
        double averageWaitingTime,
        int schedulingSwitches,
        int totalSteps,
        Instant completedAt
) {
}