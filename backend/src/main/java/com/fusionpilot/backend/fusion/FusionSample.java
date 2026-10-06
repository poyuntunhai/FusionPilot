package com.fusionpilot.backend.fusion;

import java.util.List;

public record FusionSample(
        int timeStep,
        String strategy,
        List<FusedTargetState> targetStates,
        int availableObservationCount
) {
}