package com.fusionpilot.backend.simulation;

import java.util.List;

public record SimulationRunDetail(
        String runId,
        List<TruthPoint> truth,
        List<ObservationPoint> observations,
        List<FusedStatePoint> fusedStates,
        List<ResourceAssignmentPoint> assignments,
        List<MetricPoint> metrics
) {
    public record TruthPoint(
            int timeStep,
            int targetId,
            double x,
            double y,
            double velocityX,
            double velocityY
    ) {
    }

    public record ObservationPoint(
            int timeStep,
            int targetId,
            String sourceType,
            boolean available,
            double x,
            double y,
            double confidence
    ) {
    }

    public record FusedStatePoint(
            int timeStep,
            int targetId,
            double x,
            double y,
            double velocityX,
            double velocityY,
            double uncertainty,
            double associationConfidence,
            boolean predictedOnly
    ) {
    }

    public record ResourceAssignmentPoint(
            int timeStep,
            int targetId,
            boolean allocated,
            int priorityRank,
            double priorityScore,
            String reason
    ) {
    }

    public record MetricPoint(
            int timeStep,
            double averagePositionError,
            double trackingRate,
            double resourceUtilization,
            int allocatedTargetCount,
            int unservedTargetCount
    ) {
    }
}