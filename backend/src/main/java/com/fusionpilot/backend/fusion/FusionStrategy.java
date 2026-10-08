package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.TargetState;
import com.fusionpilot.backend.scenario.FusionMethod;

import java.util.List;

/**
 * A replaceable multi-source fusion algorithm.
 *
 * <p>Strategies are stateless Spring singletons. Anything that must persist across time steps
 * lives in the {@link FusionContext} handed in by the caller, and any state must be created
 * through the context rather than stored on the bean.</p>
 */
public interface FusionStrategy {

    /** The configuration value that selects this strategy. */
    FusionMethod method();

    /** Stable identifier recorded in fusion results and the API payload. */
    String name();

    FusionResult fuse(
            FusionContext context,
            TargetState targetState,
            List<Observation> observations,
            double timeStepSeconds
    );

    /** Single-step calls and unit tests use a throwaway context. */
    default FusionResult fuse(
            TargetState targetState,
            List<Observation> observations,
            double timeStepSeconds
    ) {
        return fuse(FusionContext.stateless(), targetState, observations, timeStepSeconds);
    }

    /**
     * Prediction reference for associating the observations of the current step, built purely from
     * this run's own track: the previous fused estimate advanced by one time step.
     *
     * <p>Returns {@code null} when no track exists yet, which is the honest answer on the first
     * step — a tracker really has nothing to gate against before its first update.</p>
     *
     * @return {@code [x, y]} or {@code null}
     */
    default double[] trackPrediction(
            FusionContext context,
            TargetState targetState,
            double timeStepSeconds
    ) {
        double[] previous = context.previousFusedState(targetState.targetId());
        if (previous == null) {
            return null;
        }
        return new double[]{
                previous[0] + previous[2] * timeStepSeconds,
                previous[1] + previous[3] * timeStepSeconds
        };
    }

    /**
     * Fallback used when no observation can be fused: coast on the motion model.
     *
     * <p>Coasting starts from this run's own last fused estimate whenever one exists, so a gap in
     * the measurements produces a genuinely propagated track rather than a fresh copy of truth.
     * Only the very first step, where no track exists yet, falls back to the supplied target state.</p>
     */
    default FusionResult predictionOnly(
            FusionContext context,
            TargetState targetState,
            double timeStepSeconds
    ) {
        double[] previous = context.previousFusedState(targetState.targetId());
        if (previous == null) {
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
        return new FusionResult(
                new FusedTargetState(
                        targetState.targetId(),
                        previous[0] + previous[2] * timeStepSeconds,
                        previous[1] + previous[3] * timeStepSeconds,
                        previous[2],
                        previous[3],
                        10.0,
                        0.0,
                        targetState.timeStep(),
                        true
                ),
                List.of()
        );
    }

    /** Stateless convenience overload used by single-step calls and unit tests. */
    default FusionResult predictionOnly(TargetState targetState, double timeStepSeconds) {
        return predictionOnly(FusionContext.stateless(), targetState, timeStepSeconds);
    }

    /** An observation is usable only when it exists, is finite and carries a positive weight. */
    default boolean isUsable(Observation observation) {
        return observation.available()
                && observation.confidence() > 0.0
                && Double.isFinite(observation.x())
                && Double.isFinite(observation.y())
                && Double.isFinite(observation.confidence());
    }

    /** Observations belonging to one target that survived the usability check. */
    default List<Observation> usableObservations(List<Observation> observations) {
        return observations.stream().filter(this::isUsable).toList();
    }
}
