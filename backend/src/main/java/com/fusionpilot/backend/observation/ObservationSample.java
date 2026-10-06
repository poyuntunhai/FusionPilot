package com.fusionpilot.backend.observation;

import java.util.List;

public record ObservationSample(
        int timeStep,
        List<TargetState> targetStates,
        List<Observation> observations
) {
}