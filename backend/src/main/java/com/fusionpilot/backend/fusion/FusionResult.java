package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;

import java.util.List;

public record FusionResult(
        FusedTargetState state,
        List<Observation> usedObservations
) {
}