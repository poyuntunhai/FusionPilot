package com.fusionpilot.backend.observation;

import com.fusionpilot.backend.scenario.ExperimentConfig;
import com.fusionpilot.backend.scenario.ExperimentConfigService;
import com.fusionpilot.backend.scenario.ObservationSourceConfig;
import com.fusionpilot.backend.scenario.ObservationSourceType;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class ObservationServiceTest {

    private final ExperimentConfigService configService = new ExperimentConfigService();
    private final ObservationService observationService =
            new ObservationService(new DefaultObservationSource());

    @Test
    void sameSeedAndTimeStepProduceSameSample() {
        ExperimentConfig config = configService.defaultConfig();

        ObservationSample first = observationService.sample(config, 10);
        ObservationSample second = observationService.sample(config, 10);

        assertThat(first).isEqualTo(second);
    }

    @Test
    void sampleContainsStatesAndAllConfiguredSources() {
        ExperimentConfig config = configService.defaultConfig();

        ObservationSample sample = observationService.sample(config, 0);

        assertThat(sample.targetStates()).hasSize(config.targetCount());
        assertThat(sample.observations())
                .hasSize(config.targetCount() * config.observationSources().size());
        assertThat(sample.observations())
                .allMatch(observation -> observation.timeStep() == 0);
    }

    @Test
    void delayedSourceUsesEarlierObservedTimeStep() {
        ExperimentConfig config = configService.defaultConfig();

        ObservationSample sample = observationService.sample(config, 5);

        assertThat(sample.observations())
                .anyMatch(observation ->
                        observation.sourceType().name().equals("EO_IR")
                                && observation.observedTimeStep() == 4
                );
    }

    @Test
    void delayedSourceReportsWhereTheTargetWasNotWhereItIs() {
        // Noise and dropouts disabled so the reported position is exactly the delayed truth.
        ExperimentConfig config = configService.defaultConfig();
        ExperimentConfig delayedConfig = new ExperimentConfig(
                "delay-check",
                1,
                10,
                config.timeStepSeconds(),
                1,
                config.fusionMethod(),
                config.schedulingPolicy(),
                7L,
                List.of(new ObservationSourceConfig(ObservationSourceType.RADAR, 0.0, 0.0, 2, 0.9))
        );

        ObservationSample sample = observationService.sample(delayedConfig, 5);
        Observation observation = sample.observations().get(0);
        TargetState expected = ObservationService.stateAt(1, 3, config.timeStepSeconds());

        assertThat(observation.timeStep()).isEqualTo(5);
        assertThat(observation.observedTimeStep()).isEqualTo(3);
        assertThat(observation.x()).isEqualTo(expected.x());
        assertThat(observation.y()).isEqualTo(expected.y());
        // The stale report really is behind the current truth, not the same point.
        assertThat(observation.x()).isLessThan(ObservationService.stateAt(1, 5, config.timeStepSeconds()).x());
    }

    @Test
    void zeroDelaySourceReportsTheCurrentPosition() {
        ExperimentConfig config = configService.defaultConfig();
        ExperimentConfig immediateConfig = new ExperimentConfig(
                "no-delay-check",
                1,
                10,
                config.timeStepSeconds(),
                1,
                config.fusionMethod(),
                config.schedulingPolicy(),
                11L,
                List.of(new ObservationSourceConfig(ObservationSourceType.RADAR, 0.0, 0.0, 0, 0.9))
        );

        ObservationSample sample = observationService.sample(immediateConfig, 5);
        Observation observation = sample.observations().get(0);
        TargetState expected = ObservationService.stateAt(1, 5, config.timeStepSeconds());

        assertThat(observation.observedTimeStep()).isEqualTo(5);
        assertThat(observation.x()).isEqualTo(expected.x());
        assertThat(observation.y()).isEqualTo(expected.y());
    }
}