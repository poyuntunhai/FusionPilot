package com.fusionpilot.backend.observation;

import com.fusionpilot.backend.scenario.ExperimentConfig;
import com.fusionpilot.backend.scenario.ExperimentConfigService;
import org.junit.jupiter.api.Test;

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
}