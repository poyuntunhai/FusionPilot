package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.TargetState;
import com.fusionpilot.backend.scenario.FusionMethod;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * Confidence-weighted average: {@code x = Σ(xᵢ · cᵢ) / Σcᵢ}.
 *
 * <p>This is the project baseline. It needs no cross-step state, so the fusion context is unused.</p>
 */
@Component
public class WeightedAverageFusionStrategy implements FusionStrategy {

    @Override
    public FusionMethod method() {
        return FusionMethod.WEIGHTED_AVERAGE;
    }

    @Override
    public String name() {
        return "confidence-weighted-average";
    }

    @Override
    public FusionResult fuse(
            FusionContext context,
            TargetState targetState,
            List<Observation> observations,
            double timeStepSeconds
    ) {
        List<Observation> validObservations = usableObservations(observations);
        if (validObservations.isEmpty()) {
            return predictionOnly(context, targetState, timeStepSeconds);
        }

        double[] weighted = FusionMath.weightedMean(validObservations);
        FusedTargetState state = new FusedTargetState(
                targetState.targetId(),
                weighted[0],
                weighted[1],
                targetState.velocityX(),
                targetState.velocityY(),
                Math.max(0.01, 1.0 / weighted[2]),
                weighted[3],
                targetState.timeStep(),
                false
        );
        return new FusionResult(state, validObservations);
    }
}
