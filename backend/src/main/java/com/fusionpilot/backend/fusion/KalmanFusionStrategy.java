package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.TargetState;
import com.fusionpilot.backend.scenario.FusionMethod;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * Constant-velocity Kalman filter, one filter per target, updated sequentially by every usable
 * observation in arrival order.
 *
 * <p>Unlike the averaging strategies this one carries memory across time steps, so it keeps its
 * state in the {@link FusionContext}. Two consequences are worth remembering when reading results:</p>
 * <ul>
 *   <li>It is the only strategy that <b>estimates</b> velocity rather than copying the true one,
 *       so its first few steps are worse than the baselines while the filter converges.</li>
 *   <li>A step with no usable observation is not a gap in the estimate — the filter coasts on the
 *       prediction, which is exactly the behaviour the baselines cannot express.</li>
 * </ul>
 */
@Component
public class KalmanFusionStrategy implements FusionStrategy {

    @Override
    public FusionMethod method() {
        return FusionMethod.KALMAN_FILTER;
    }

    @Override
    public String name() {
        return "constant-velocity-kalman";
    }

    @Override
    public FusionResult fuse(
            FusionContext context,
            TargetState targetState,
            List<Observation> observations,
            double timeStepSeconds
    ) {
        List<Observation> validObservations = usableObservations(observations);
        KalmanTargetFilter filter = context.memory(targetState.targetId(), KalmanTargetFilter::new);
        List<Observation> usedObservations = new ArrayList<>();

        if (!filter.isSeeded()) {
            if (validObservations.isEmpty()) {
                // Nothing has been measured yet, so there is no belief to seed. Coast instead,
                // and leave the filter unseeded so it still adopts its first real measurement.
                return predictionOnly(context, targetState, timeStepSeconds);
            }
            // First measurement defines the initial belief; it is consumed, not re-applied.
            Observation seedObservation = validObservations.get(0);
            filter.seed(
                    seedObservation.x(),
                    seedObservation.y(),
                    context.measurementNoise(seedObservation.sourceType())
            );
            usedObservations.add(seedObservation);
            for (int index = 1; index < validObservations.size(); index++) {
                Observation observation = validObservations.get(index);
                filter.update(
                        observation.x(),
                        observation.y(),
                        context.measurementNoise(observation.sourceType())
                );
                usedObservations.add(observation);
            }
        } else {
            filter.predict(timeStepSeconds);
            for (Observation observation : validObservations) {
                filter.update(
                        observation.x(),
                        observation.y(),
                        context.measurementNoise(observation.sourceType())
                );
                usedObservations.add(observation);
            }
        }

        boolean predictedOnly = usedObservations.isEmpty();
        FusedTargetState state = new FusedTargetState(
                targetState.targetId(),
                filter.x(),
                filter.y(),
                filter.velocityX(),
                filter.velocityY(),
                filter.positionUncertainty(),
                FusionMath.meanConfidence(usedObservations),
                targetState.timeStep(),
                predictedOnly
        );
        return new FusionResult(state, usedObservations);
    }
}
