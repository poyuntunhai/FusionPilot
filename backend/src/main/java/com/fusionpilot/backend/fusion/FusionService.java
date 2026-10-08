package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.ObservationSample;
import com.fusionpilot.backend.observation.TargetState;
import com.fusionpilot.backend.scenario.FusionMethod;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.EnumMap;
import java.util.List;
import java.util.Map;

@Service
public class FusionService {

    private final Map<FusionMethod, FusionStrategy> strategies = new EnumMap<>(FusionMethod.class);
    private final FusionStrategy fallback;

    /** Single-strategy wiring, kept for unit tests and minimal configurations. */
    public FusionService(FusionStrategy strategy) {
        this(List.of(strategy));
    }

    @Autowired
    public FusionService(List<FusionStrategy> strategies) {
        for (FusionStrategy strategy : strategies) {
            this.strategies.put(strategy.method(), strategy);
        }
        this.fallback = this.strategies.getOrDefault(FusionMethod.WEIGHTED_AVERAGE, strategies.get(0));
    }

    /** Single-time-step call with the project baseline and no cross-step memory. */
    public FusionSample fuse(ObservationSample sample, double timeStepSeconds) {
        return fuse(sample, timeStepSeconds, FusionMethod.WEIGHTED_AVERAGE, FusionContext.stateless());
    }

    public FusionSample fuse(
            ObservationSample sample,
            double timeStepSeconds,
            FusionMethod method,
            FusionContext context
    ) {
        FusionStrategy strategy = strategyFor(method);
        List<FusedTargetState> fusedStates = sample.targetStates().stream()
                .map(target -> strategy
                        .fuse(context, target, observationsFor(sample, target), timeStepSeconds)
                        .state())
                .toList();
        // Publish this step's estimates only after every target is fused, so the next step's
        // association and coasting predict from the track rather than from ground truth.
        for (FusedTargetState state : fusedStates) {
            context.recordFusedState(
                    state.targetId(),
                    state.x(),
                    state.y(),
                    state.velocityX(),
                    state.velocityY()
            );
        }

        int availableObservationCount = (int) sample.observations().stream()
                .filter(Observation::available)
                .count();
        return new FusionSample(
                sample.timeStep(),
                strategy.name(),
                fusedStates,
                availableObservationCount
        );
    }

    /** The algorithm a given configuration value resolves to, for reporting and diagnostics. */
    public String strategyName(FusionMethod method) {
        return strategyFor(method).name();
    }

    private FusionStrategy strategyFor(FusionMethod method) {
        FusionStrategy strategy = strategies.get(method);
        return strategy == null ? fallback : strategy;
    }

    private List<Observation> observationsFor(ObservationSample sample, TargetState target) {
        return sample.observations().stream()
                .filter(observation -> observation.targetId() == target.targetId())
                .toList();
    }
}
