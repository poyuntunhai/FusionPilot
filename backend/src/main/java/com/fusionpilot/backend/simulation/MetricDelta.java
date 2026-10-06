package com.fusionpilot.backend.simulation;

public record MetricDelta(
        double averagePositionErrorDelta,
        double trackingRateDelta,
        double resourceUtilizationDelta,
        double averageWaitingTimeDelta,
        int schedulingSwitchesDelta
) {
}