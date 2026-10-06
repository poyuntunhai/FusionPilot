package com.fusionpilot.backend.observation;

import com.fusionpilot.backend.scenario.ObservationSourceType;

public record Observation(
        int targetId,
        ObservationSourceType sourceType,
        int timeStep,
        int observedTimeStep,
        double x,
        double y,
        double confidence,
        boolean available
) {
}