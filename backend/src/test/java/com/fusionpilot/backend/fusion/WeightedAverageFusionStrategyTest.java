package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.TargetState;
import com.fusionpilot.backend.scenario.ObservationSourceType;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class WeightedAverageFusionStrategyTest {

    private final WeightedAverageFusionStrategy strategy = new WeightedAverageFusionStrategy();

    @Test
    void shouldWeightPositionsByObservationConfidence() {
        TargetState target = new TargetState(1, 100.0, 50.0, 2.0, 1.0, 3);
        List<Observation> observations = List.of(
                new Observation(1, ObservationSourceType.RADAR, 3, 3, 110.0, 50.0, 0.8, true),
                new Observation(1, ObservationSourceType.EO_IR, 3, 3, 90.0, 70.0, 0.2, true)
        );

        FusionResult result = strategy.fuse(target, observations, 1.0);

        assertThat(result.state().x()).isEqualTo(106.0);
        assertThat(result.state().y()).isEqualTo(54.0);
        assertThat(result.state().predictedOnly()).isFalse();
        assertThat(result.usedObservations()).hasSize(2);
    }

    @Test
    void shouldUseMotionPredictionWhenNoObservationIsAvailable() {
        TargetState target = new TargetState(1, 100.0, 50.0, 2.0, 1.0, 3);
        List<Observation> observations = List.of(
                new Observation(1, ObservationSourceType.RADAR, 3, 3, 0.0, 0.0, 0.9, false)
        );

        FusionResult result = strategy.fuse(target, observations, 2.0);

        assertThat(result.state().x()).isEqualTo(104.0);
        assertThat(result.state().y()).isEqualTo(52.0);
        assertThat(result.state().predictedOnly()).isTrue();
        assertThat(result.state().associationConfidence()).isZero();
        assertThat(result.usedObservations()).isEmpty();
    }
}