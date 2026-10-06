package com.fusionpilot.backend.persistence;

import com.fusionpilot.backend.scenario.ExperimentConfig;
import com.fusionpilot.backend.scenario.ExperimentConfigService;
import com.fusionpilot.backend.scenario.SchedulingPolicy;
import com.fusionpilot.backend.simulation.SimulationResult;
import com.fusionpilot.backend.simulation.SimulationRunDetail;
import com.fusionpilot.backend.simulation.SimulationService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
class JdbcSimulationDetailQueryRepositoryTest {

    @Autowired
    private SimulationService simulationService;

    @Autowired
    private ExperimentConfigService configService;

    @Test
    void shouldReadNormalizedSimulationDetailsForPlayback() {
        SimulationResult result = simulationService.run(shortConfig());

        SimulationRunDetail detail = simulationService.detail(result.runId());

        assertThat(detail.runId()).isEqualTo(result.runId());
        assertThat(detail.truth()).hasSize(6);
        assertThat(detail.observations()).hasSize(18);
        assertThat(detail.fusedStates()).hasSize(6);
        assertThat(detail.assignments()).hasSize(6);
        assertThat(detail.metrics()).hasSize(3);
        assertThat(detail.metrics().get(0).timeStep()).isZero();
    }

    private ExperimentConfig shortConfig() {
        ExperimentConfig config = configService.defaultConfig();
        return new ExperimentConfig(
                config.scenarioName(),
                2,
                3,
                config.timeStepSeconds(),
                1,
                config.fusionMethod(),
                SchedulingPolicy.PRIORITY,
                config.randomSeed(),
                config.observationSources()
        );
    }
}