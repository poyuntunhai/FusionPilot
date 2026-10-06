package com.fusionpilot.backend.simulation;

public record StepMetrics(
        double averagePositionError,
        double trackingRate,
        double resourceUtilization,
        int allocatedTargetCount,
        int unservedTargetCount
) {
}