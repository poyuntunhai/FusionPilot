package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.TargetState;
import org.springframework.stereotype.Component;

import java.util.List;

@Component
public class WeightedAverageFusionStrategy implements FusionStrategy {

    @Override
    public String name() {
        return "confidence-weighted-average";
    }

    @Override
    public FusionResult fuse(
            TargetState targetState,
            List<Observation> observations,
            double timeStepSeconds
    ) {
        List<Observation> validObservations = observations.stream()
                .filter(this::isValid)
                .toList();

        if (validObservations.isEmpty()) {
            TargetState predicted = targetState.advance(timeStepSeconds);
            return new FusionResult(
                    new FusedTargetState(
                            predicted.targetId(),
                            predicted.x(),
                            predicted.y(),
                            predicted.velocityX(),
                            predicted.velocityY(),
                            10.0,
                            0.0,
                            predicted.timeStep(),
                            true
                    ),
                    List.of()
            );
        }

        double totalWeight = validObservations.stream()
                .mapToDouble(Observation::confidence)
                .sum();
        double fusedX = validObservations.stream()
                .mapToDouble(observation -> observation.x() * observation.confidence())
                .sum() / totalWeight;
        double fusedY = validObservations.stream()
                .mapToDouble(observation -> observation.y() * observation.confidence())
                .sum() / totalWeight;
        double averageConfidence = validObservations.stream()
                .mapToDouble(observation -> observation.confidence() * observation.confidence())
                .sum() / totalWeight;

        FusedTargetState state = new FusedTargetState(
                targetState.targetId(),
                fusedX,
                fusedY,
                targetState.velocityX(),
                targetState.velocityY(),
                Math.max(0.01, 1.0 / totalWeight),
                averageConfidence,
                targetState.timeStep(),
                false
        );
        return new FusionResult(state, validObservations);
    }

    private boolean isValid(Observation observation) {
        return observation.available()
                && observation.confidence() > 0.0
                && Double.isFinite(observation.x())
                && Double.isFinite(observation.y())
                && Double.isFinite(observation.confidence());
    }
}