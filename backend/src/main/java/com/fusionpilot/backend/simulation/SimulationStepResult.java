package com.fusionpilot.backend.simulation;

import com.fusionpilot.backend.fusion.FusedTargetState;
import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.TargetState;
import com.fusionpilot.backend.scheduling.SchedulingResult;

import java.util.List;

public record SimulationStepResult(
        int timeStep,
        List<TargetState> trueStates,
        List<Observation> observations,
        List<FusedTargetState> fusedStates,
        SchedulingResult scheduling,
        StepMetrics metrics
) {
}