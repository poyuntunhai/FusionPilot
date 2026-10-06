package com.fusionpilot.backend.simulation;

public record AggregateMetrics(
        double averagePositionError,
        double trackingRate,
        double resourceUtilization,
        double averageWaitingTime,
        int schedulingSwitches,
        int totalSteps
) {
}