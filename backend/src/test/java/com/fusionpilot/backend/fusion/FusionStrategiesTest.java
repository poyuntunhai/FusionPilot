package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.ObservationService;
import com.fusionpilot.backend.observation.TargetState;
import com.fusionpilot.backend.scenario.FusionMethod;
import com.fusionpilot.backend.scenario.ObservationSourceType;
import org.junit.jupiter.api.Test;

import java.util.EnumSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

class FusionStrategiesTest {

    private static final double RADAR_NOISE = 3.0;
    private static final double EO_IR_NOISE = 5.0;

    private final FusionService service = new FusionService(List.of(
            new WeightedAverageFusionStrategy(),
            new SimpleAverageFusionStrategy(),
            new NearestNeighborFusionStrategy(),
            new DistanceGatedFusionStrategy(),
            new KalmanFusionStrategy()
    ));

    private final FusionContext context = new FusionContext(Map.of(
            ObservationSourceType.RADAR, RADAR_NOISE,
            ObservationSourceType.EO_IR, EO_IR_NOISE
    ));

    @Test
    void everyConfiguredMethodResolvesToItsOwnStrategy() {
        Set<String> names = EnumSet.allOf(FusionMethod.class).stream()
                .map(service::strategyName)
                .collect(Collectors.toSet());

        assertThat(names).hasSize(FusionMethod.values().length);
    }

    @Test
    void simpleAverageIgnoresConfidenceWhileWeightedAverageDoesNot() {
        TargetState target = new TargetState(1, 100.0, 50.0, 2.0, 1.0, 0);
        List<Observation> observations = List.of(
                new Observation(1, ObservationSourceType.RADAR, 0, 0, 104.0, 50.0, 0.9, true),
                new Observation(1, ObservationSourceType.EO_IR, 0, 0, 94.0, 60.0, 0.3, true)
        );

        FusionResult simple = new SimpleAverageFusionStrategy().fuse(context, target, observations, 1.0);
        FusionResult weighted = new WeightedAverageFusionStrategy().fuse(context, target, observations, 1.0);

        assertThat(simple.state().x()).isEqualTo(99.0);
        assertThat(simple.state().y()).isEqualTo(55.0);
        // The high-confidence radar track pulls the weighted estimate towards itself.
        assertThat(weighted.state().x()).isCloseTo(101.5, within(1e-9));
        assertThat(weighted.state().x()).isGreaterThan(simple.state().x());
    }

    @Test
    void firstStepBootstrapsBecauseNoTrackExistsYet() {
        // No prior fused state, so there is nothing to associate against. Nearest-neighbour must
        // fall back to trust, and the gate must not reject anything it cannot judge.
        TargetState target = new TargetState(1, 100.0, 50.0, 2.0, 1.0, 0);
        List<Observation> observations = List.of(
                new Observation(1, ObservationSourceType.EO_IR, 0, 0, 200.0, 150.0, 0.95, true),
                new Observation(1, ObservationSourceType.RADAR, 0, 0, 102.0, 51.0, 0.60, true)
        );

        FusionResult nearest = new NearestNeighborFusionStrategy().fuse(context, target, observations, 1.0);
        FusionResult gated = new DistanceGatedFusionStrategy().fuse(context, target, observations, 1.0);

        // Bootstrapping picks the most trusted source, not the nearest one.
        assertThat(nearest.state().x()).isEqualTo(200.0);
        assertThat(nearest.usedObservations().get(0).sourceType()).isEqualTo(ObservationSourceType.EO_IR);
        assertThat(gated.usedObservations()).hasSize(2);
    }

    @Test
    void associationPredictsFromTheTrackNotFromGroundTruth() {
        // The track is stale and sits at x = 129 while the target is really at x = 100.
        // A truth-referenced selector would keep the sample at 101; a track-referenced one must
        // keep the sample at 129 even though it is far less trusted.
        context.recordFusedState(1, 129.0, 50.0, 0.0, 0.0);
        TargetState truth = new TargetState(1, 100.0, 50.0, 10.0, 0.0, 1);
        List<Observation> observations = List.of(
                new Observation(1, ObservationSourceType.RADAR, 1, 1, 101.0, 50.0, 0.90, true),
                new Observation(1, ObservationSourceType.RADAR, 1, 1, 129.0, 50.0, 0.30, true)
        );

        FusionResult nearest = new NearestNeighborFusionStrategy().fuse(context, truth, observations, 1.0);

        assertThat(nearest.state().x()).isEqualTo(129.0);
    }

    @Test
    void distanceGateIsCentredOnTheTrackPrediction() {
        // Track prediction is (129, 50). Radar noise 3.0 gives a gate radius of 9.0, so the
        // sample at 101 is 28 units out and must be dropped, while the one at 130 survives.
        context.recordFusedState(1, 129.0, 50.0, 0.0, 0.0);
        TargetState truth = new TargetState(1, 100.0, 50.0, 10.0, 0.0, 1);
        List<Observation> observations = List.of(
                new Observation(1, ObservationSourceType.RADAR, 1, 1, 101.0, 50.0, 0.90, true),
                new Observation(1, ObservationSourceType.RADAR, 1, 1, 130.0, 50.0, 0.30, true)
        );

        FusionResult gated = new DistanceGatedFusionStrategy().fuse(context, truth, observations, 1.0);
        FusionResult baseline = new WeightedAverageFusionStrategy().fuse(context, truth, observations, 1.0);

        assertThat(gated.usedObservations()).hasSize(1);
        assertThat(gated.state().x()).isCloseTo(130.0, within(1e-9));
        // The baseline has no gate and is dragged towards the rejected sample.
        assertThat(baseline.state().x()).isLessThan(gated.state().x());
    }

    @Test
    void coastingPropagatesTheOwnTrackRatherThanCopyingTruth() {
        // Track sits at (100, 50) moving (2, 1); the target is really at (200, 300).
        context.recordFusedState(1, 100.0, 50.0, 2.0, 1.0);
        TargetState truth = new TargetState(1, 200.0, 300.0, 2.0, 1.0, 5);
        List<Observation> dropped = List.of(
                new Observation(1, ObservationSourceType.RADAR, 5, 5, 0.0, 0.0, 0.0, false)
        );

        FusionResult result = new WeightedAverageFusionStrategy().fuse(context, truth, dropped, 2.0);

        assertThat(result.state().predictedOnly()).isTrue();
        // Propagated from the track: 100 + 2 * 2 and 50 + 1 * 2.
        assertThat(result.state().x()).isEqualTo(104.0);
        assertThat(result.state().y()).isEqualTo(52.0);
        // Not the truth-advanced position, which would be (204, 302).
        assertThat(result.state().x()).isNotEqualTo(204.0);
    }

    @Test
    void everyStrategyFallsBackToMotionPredictionWithoutObservations() {
        TargetState target = new TargetState(1, 100.0, 50.0, 2.0, 1.0, 4);
        List<Observation> dropped = List.of(
                new Observation(1, ObservationSourceType.RADAR, 4, 4, 0.0, 0.0, 0.0, false)
        );

        for (FusionStrategy strategy : List.of(
                new WeightedAverageFusionStrategy(),
                new SimpleAverageFusionStrategy(),
                new NearestNeighborFusionStrategy(),
                new DistanceGatedFusionStrategy(),
                new KalmanFusionStrategy()
        )) {
            FusionResult result = strategy.fuse(context, target, dropped, 2.0);

            assertThat(result.state().predictedOnly())
                    .as("%s should coast on the motion model", strategy.name())
                    .isTrue();
            assertThat(result.state().x()).isEqualTo(104.0);
            assertThat(result.state().y()).isEqualTo(52.0);
        }
    }

    @Test
    void kalmanFilterRecoversTheTrueVelocityFromNoiselessMeasurements() {
        // Decisive check on the filter maths itself: with clean measurements the state must
        // converge exactly onto the constant-velocity truth. Any residual here would be a bug
        // rather than a tuning question.
        KalmanFusionStrategy kalman = new KalmanFusionStrategy();
        FusionContext runContext = new FusionContext(Map.of(ObservationSourceType.RADAR, 1.0));

        FusedTargetState estimate = null;
        for (int timeStep = 0; timeStep < 30; timeStep++) {
            TargetState truth = ObservationService.stateAt(2, timeStep, 1.0);
            Observation exact = new Observation(
                    2, ObservationSourceType.RADAR, timeStep, timeStep,
                    truth.x(), truth.y(), 1.0, true
            );
            estimate = kalman.fuse(runContext, truth, List.of(exact), 1.0).state();
        }

        // Target 2 flies at exactly (3.0, 1.5) units per second.
        assertThat(estimate.velocityX()).isCloseTo(3.0, within(1e-4));
        assertThat(estimate.velocityY()).isCloseTo(1.5, within(1e-4));
        assertThat(estimate.uncertainty()).isLessThan(1.0);
    }

    @Test
    void kalmanFilterEstimatesVelocityAndBeatsTheRawMeasurementError() {
        KalmanFusionStrategy kalman = new KalmanFusionStrategy();
        // Reusable per-target memory, exactly as a single simulation run would use it.
        FusionContext runContext = new FusionContext(Map.of(ObservationSourceType.RADAR, 4.0));

        // Fixed, repeating offsets instead of random draws so this test can never flake.
        double[] offsets = {4.0, -3.4, 2.6, -2.1, 3.2, -4.4, 1.6, -0.9, 2.1, -2.6,
                            1.1, -1.4, 3.4, -2.9, 0.6, -0.7, 2.4, -1.9, 1.3, -2.2};

        FusedTargetState estimate = null;
        double rawErrorSum = 0.0;
        for (int timeStep = 0; timeStep < offsets.length; timeStep++) {
            TargetState truth = ObservationService.stateAt(1, timeStep, 1.0);
            double measuredX = truth.x() + offsets[timeStep];
            double measuredY = truth.y() + offsets[(timeStep + 7) % offsets.length];
            rawErrorSum += Math.hypot(measuredX - truth.x(), measuredY - truth.y());

            Observation measurement = new Observation(
                    1, ObservationSourceType.RADAR, timeStep, timeStep,
                    measuredX, measuredY, 0.9, true
            );
            estimate = kalman.fuse(runContext, truth, List.of(measurement), 1.0).state();
        }

        TargetState truth = ObservationService.stateAt(1, offsets.length - 1, 1.0);
        double estimateError = Math.hypot(estimate.x() - truth.x(), estimate.y() - truth.y());
        double meanRawError = rawErrorSum / offsets.length;

        // Target 1 flies at exactly (2.5, 1.25) units per second.
        assertThat(estimate.velocityX()).isCloseTo(2.5, within(0.75));
        assertThat(estimate.velocityY()).isCloseTo(1.25, within(0.75));
        assertThat(estimate.predictedOnly()).isFalse();
        // Smoothing the measurements must beat the raw measurement error.
        assertThat(estimateError).isLessThan(meanRawError);
    }
}
