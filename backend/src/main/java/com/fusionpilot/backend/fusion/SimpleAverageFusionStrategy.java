package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.TargetState;
import com.fusionpilot.backend.scenario.FusionMethod;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * Unweighted arithmetic mean of every usable observation.
 *
 * <p>Serves as the naive baseline: it ignores how much each source is trusted, so a noisy
 * prior-knowledge track pulls the estimate just as hard as a clean radar track.</p>
 */
@Component
public class SimpleAverageFusionStrategy implements FusionStrategy {

    @Override
    public FusionMethod method() {
        return FusionMethod.SIMPLE_AVERAGE;
    }

    @Override
    public String name() {
        return "simple-average";
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

        int count = validObservations.size();
        double x = validObservations.stream().mapToDouble(Observation::x).average().orElse(0.0);
        double y = validObservations.stream().mapToDouble(Observation::y).average().orElse(0.0);

        FusedTargetState state = new FusedTargetState(
                targetState.targetId(),
                x,
                y,
                targetState.velocityX(),
                targetState.velocityY(),
                Math.max(0.01, 1.0 / count),
                FusionMath.meanConfidence(validObservations),
                targetState.timeStep(),
                false
        );
        return new FusionResult(state, validObservations);
    }
}
