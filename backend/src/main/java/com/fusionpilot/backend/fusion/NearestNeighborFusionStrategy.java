package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.TargetState;
import com.fusionpilot.backend.scenario.FusionMethod;
import org.springframework.stereotype.Component;

import java.util.Comparator;
import java.util.List;

/**
 * Nearest-neighbour association: keep only the single observation closest to the
 * constant-velocity prediction and discard the rest.
 *
 * <p>This is the classic hard-association baseline — "trust whoever is nearest". It is cheap but
 * throws away the corroboration that a second source would provide, so it is noticeably noisier
 * than the averaging strategies.</p>
 *
 * <p>Association runs against this run's own track prediction, never against ground truth: the
 * reference is the previous fused estimate advanced by one time step. On the first step, before a
 * track exists, the highest-confidence observation is chosen. An earlier ground-truth reference
 * behaved like an oracle and made this strategy look better than it actually is.</p>
 */
@Component
public class NearestNeighborFusionStrategy implements FusionStrategy {

    @Override
    public FusionMethod method() {
        return FusionMethod.NEAREST_NEIGHBOR;
    }

    @Override
    public String name() {
        return "nearest-neighbor";
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

        // Reference comes from this run's own track. With no track yet there is nothing to
        // associate against, so the most trusted measurement is a legitimate bootstrap.
        double[] reference = trackPrediction(context, targetState, timeStepSeconds);
        Observation nearest = (reference == null
                ? validObservations.stream().max(Comparator.comparingDouble(Observation::confidence))
                : validObservations.stream().min(Comparator.comparingDouble(observation ->
                        FusionMath.squaredDistance(
                                observation.x(),
                                observation.y(),
                                reference[0],
                                reference[1]
                        ))))
                .orElseThrow();

        FusedTargetState state = new FusedTargetState(
                targetState.targetId(),
                nearest.x(),
                nearest.y(),
                targetState.velocityX(),
                targetState.velocityY(),
                Math.max(0.01, 1.0 / nearest.confidence()),
                nearest.confidence(),
                targetState.timeStep(),
                false
        );
        return new FusionResult(state, List.of(nearest));
    }
}
