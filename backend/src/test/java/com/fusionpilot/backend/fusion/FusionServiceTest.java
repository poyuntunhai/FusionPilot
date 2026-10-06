package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;
import com.fusionpilot.backend.observation.ObservationSample;
import com.fusionpilot.backend.observation.TargetState;
import com.fusionpilot.backend.scenario.ObservationSourceType;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class FusionServiceTest {

    @Test
    void shouldFuseEachTargetIndependently() {
        FusionService service = new FusionService(new WeightedAverageFusionStrategy());
        ObservationSample sample = new ObservationSample(
                2,
                List.of(
                        new TargetState(1, 100.0, 50.0, 2.0, 1.0, 2),
                        new TargetState(2, 200.0, 80.0, 2.5, 1.5, 2)
                ),
                List.of(
                        new Observation(1, ObservationSourceType.RADAR, 2, 2, 101.0, 51.0, 1.0, true),
                        new Observation(2, ObservationSourceType.EO_IR, 2, 2, 198.0, 81.0, 1.0, true)
                )
        );

        FusionSample result = service.fuse(sample, 1.0);

        assertThat(result.strategy()).isEqualTo("confidence-weighted-average");
        assertThat(result.availableObservationCount()).isEqualTo(2);
        assertThat(result.targetStates()).extracting(FusedTargetState::targetId)
                .containsExactly(1, 2);
        assertThat(result.targetStates().get(0).x()).isEqualTo(101.0);
        assertThat(result.targetStates().get(1).x()).isEqualTo(198.0);
    }
}