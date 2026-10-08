package com.fusionpilot.backend.persistence;

import java.time.Instant;

/**
 * One row of a user's saved history. Deliberately lightweight: it carries enough to render the
 * list and decide whether to reload the full result, but not the step-level detail.
 */
public record SimulationRunSummary(
        String runId,
        String scenarioName,
        int targetCount,
        int simulationSteps,
        String schedulingPolicy,
        String fusionMethod,
        long randomSeed,
        double averagePositionError,
        double trackingRate,
        double resourceUtilization,
        double averageWaitingTime,
        int schedulingSwitches,
        int totalSteps,
        Instant completedAt,
        Instant savedAt
) {
}
