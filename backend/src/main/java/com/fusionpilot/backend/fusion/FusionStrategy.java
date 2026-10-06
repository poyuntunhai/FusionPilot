package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.TargetState;

import java.util.List;

public interface FusionStrategy {

    String name();

    FusionResult fuse(
            TargetState targetState,
            List<Observation> observations,
            double timeStepSeconds
    );
}