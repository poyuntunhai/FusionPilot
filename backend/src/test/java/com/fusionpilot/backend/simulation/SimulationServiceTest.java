package com.fusionpilot.backend.simulation;

import com.fusionpilot.backend.fusion.FusionService;
import com.fusionpilot.backend.fusion.WeightedAverageFusionStrategy;
import com.fusionpilot.backend.observation.DefaultObservationSource;
import com.fusionpilot.backend.observation.ObservationService;
import com.fusionpilot.backend.scenario.ExperimentConfig;
import com.fusionpilot.backend.scenario.ExperimentConfigService;
import com.fusionpilot.backend.scenario.SchedulingPolicy;
import com.fusionpilot.backend.scheduling.PrioritySchedulingStrategy;
import com.fusionpilot.backend.scheduling.RoundRobinSchedulingStrategy;
import com.fusionpilot.backend.scheduling.SchedulingService;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class SimulationServiceTest {

    @Test
    void shouldRunDeterministicMultiStepSimulation() {
        SimulationService service = service();
        ExperimentConfig config = shortConfig(SchedulingPolicy.ROUND_ROBIN);

        SimulationResult first = service.run(config);
        SimulationResult second = service.run(config);

        assertThat(first.steps()).hasSize(4);
        assertThat(first.metrics()).isEqualTo(second.metrics());
        assertThat(first.steps().get(0).trueStates()).isEqualTo(
                second.steps().get(0).trueStates()
        );
        assertThat(first.steps().get(0).observations()).isEqualTo(
                second.steps().get(0).observations()
        );
    }

    @Test
    void shouldCompareRoundRobinAndPriority() {
        SimulationService service = service();
        StrategyComparisonResult result = service.compare(
                shortConfig(SchedulingPolicy.ROUND_ROBIN)
        );

        assertThat(result.roundRobin().config().schedulingPolicy())
                .isEqualTo(SchedulingPolicy.ROUND_ROBIN);
        assertThat(result.priority().config().schedulingPolicy())
                .isEqualTo(SchedulingPolicy.PRIORITY);
        assertThat(result.priorityMinusRoundRobin()).isNotNull();
    }

    private SimulationService service() {
        ObservationService observationService = new ObservationService(
                new DefaultObservationSource()
        );
        FusionService fusionService = new FusionService(
                new WeightedAverageFusionStrategy()
        );
        SchedulingService schedulingService = new SchedulingService(List.of(
                new RoundRobinSchedulingStrategy(),
                new PrioritySchedulingStrategy()
        ));
        return new SimulationService(
                observationService,
                fusionService,
                schedulingService,
                new SimulationResultStore()
        );
    }

    private ExperimentConfig shortConfig(SchedulingPolicy policy) {
        ExperimentConfig defaultConfig = new ExperimentConfigService().defaultConfig();
        return new ExperimentConfig(
                defaultConfig.scenarioName(),
                3,
                4,
                defaultConfig.timeStepSeconds(),
                2,
                defaultConfig.fusionMethod(),
                policy,
                defaultConfig.randomSeed(),
                defaultConfig.observationSources()
        );
    }
}