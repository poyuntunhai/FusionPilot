package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.TargetState;
import com.fusionpilot.backend.scenario.FusionMethod;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * Distance-gated confidence-weighted average.
 *
 * <p>Before averaging, every observation is checked against a gate centred on this run's own track
 * prediction — the previous fused estimate advanced by one step, never ground truth. Anything
 * outside {@link #GATE_SIGMA} times the source's own position noise is treated as an outlier and
 * dropped. Surviving observations are then combined with the same confidence weighting as the
 * baseline.</p>
 *
 * <p>Two assumptions worth knowing:</p>
 * <ul>
 *   <li>The gate radius uses the measurement noise only. It does not add an
 *       extrapolation-uncertainty term, so the gate is deliberately loose.</li>
 *   <li>On the first step there is no track, so no gate is applied and every observation is
 *       accepted. A tracker cannot reject anything before its first update.</li>
 * </ul>
 */
@Component
public class DistanceGatedFusionStrategy implements FusionStrategy {

    /** Gate radius expressed as a multiple of the source's position noise. */
    static final double GATE_SIGMA = 3.0;

    @Override
    public FusionMethod method() {
        return FusionMethod.DISTANCE_GATED;
    }

    @Override
    public String name() {
        return "distance-gated-weighted-average";
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

        // Gate around this run's own prediction. Without a track yet there is nothing to gate
        // against, so the first step accepts everything rather than inventing a reference.
        double[] reference = trackPrediction(context, targetState, timeStepSeconds);
        List<Observation> accepted = reference == null
                ? validObservations
                : validObservations.stream()
                        .filter(observation -> {
                            double gate = GATE_SIGMA
                                    * context.measurementNoise(observation.sourceType());
                            return FusionMath.squaredDistance(
                                    observation.x(),
                                    observation.y(),
                                    reference[0],
                                    reference[1]
                            ) <= gate * gate;
                        })
                        .toList();

        if (accepted.isEmpty()) {
            return predictionOnly(context, targetState, timeStepSeconds);
        }

        double[] weighted = FusionMath.weightedMean(accepted);
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
        return new FusionResult(state, accepted);
    }
}
