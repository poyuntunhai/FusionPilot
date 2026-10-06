package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.ObservationSample;
import com.fusionpilot.backend.observation.TargetState;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class FusionService {

    private final FusionStrategy fusionStrategy;

    public FusionService(FusionStrategy fusionStrategy) {
        this.fusionStrategy = fusionStrategy;
    }

    public FusionSample fuse(ObservationSample sample, double timeStepSeconds) {
        List<FusedTargetState> fusedStates = sample.targetStates().stream()
                .map(target -> fuseTarget(target, sample.observations(), timeStepSeconds))
                .toList();
        int availableObservationCount = (int) sample.observations().stream()
                .filter(Observation::available)
                .count();
        return new FusionSample(
                sample.timeStep(),
                fusionStrategy.name(),
                fusedStates,
                availableObservationCount
        );
    }

    private FusedTargetState fuseTarget(
            TargetState target,
            List<Observation> observations,
            double timeStepSeconds
    ) {
        List<Observation> targetObservations = observations.stream()
                .filter(observation -> observation.targetId() == target.targetId())
                .toList();
        return fusionStrategy.fuse(target, targetObservations, timeStepSeconds).state();
    }
}