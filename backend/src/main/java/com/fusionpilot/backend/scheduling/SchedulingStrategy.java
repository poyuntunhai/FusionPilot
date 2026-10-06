package com.fusionpilot.backend.scheduling;

import com.fusionpilot.backend.fusion.FusedTargetState;
import com.fusionpilot.backend.scenario.SchedulingPolicy;

import java.util.List;

public interface SchedulingStrategy {

    SchedulingPolicy policy();

    SchedulingResult schedule(
            List<FusedTargetState> targetStates,
            int availableResources,
            int timeStep
    );
}