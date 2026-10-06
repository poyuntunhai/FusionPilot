package com.fusionpilot.backend.simulation;

import com.fusionpilot.backend.fusion.FusionSample;
import com.fusionpilot.backend.fusion.FusionService;
import com.fusionpilot.backend.fusion.FusedTargetState;
import com.fusionpilot.backend.observation.ObservationSample;
import com.fusionpilot.backend.observation.ObservationService;
import com.fusionpilot.backend.observation.TargetState;
import com.fusionpilot.backend.persistence.JdbcSimulationDetailQueryRepository;
import com.fusionpilot.backend.persistence.SimulationRunSummary;
import com.fusionpilot.backend.scenario.ExperimentConfig;
import com.fusionpilot.backend.scenario.SchedulingPolicy;
import com.fusionpilot.backend.scheduling.SchedulingResult;
import com.fusionpilot.backend.scheduling.SchedulingService;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
public class SimulationService {

    private final ObservationService observationService;
    private final FusionService fusionService;
    private final SchedulingService schedulingService;
    private final SimulationResultStore resultStore;
    private final JdbcSimulationDetailQueryRepository detailQueryRepository;

    public SimulationService(
            ObservationService observationService,
            FusionService fusionService,
            SchedulingService schedulingService,
            SimulationResultStore resultStore
    ) {
        this(
                observationService,
                fusionService,
                schedulingService,
                resultStore,
                (JdbcSimulationDetailQueryRepository) null
        );
    }

    @Autowired
    public SimulationService(
            ObservationService observationService,
            FusionService fusionService,
            SchedulingService schedulingService,
            SimulationResultStore resultStore,
            ObjectProvider<JdbcSimulationDetailQueryRepository> detailQueryProvider
    ) {
        this(
                observationService,
                fusionService,
                schedulingService,
                resultStore,
                detailQueryProvider.getIfAvailable()
        );
    }

    private SimulationService(
            ObservationService observationService,
            FusionService fusionService,
            SchedulingService schedulingService,
            SimulationResultStore resultStore,
            JdbcSimulationDetailQueryRepository detailQueryRepository
    ) {
        this.observationService = observationService;
        this.fusionService = fusionService;
        this.schedulingService = schedulingService;
        this.resultStore = resultStore;
        this.detailQueryRepository = detailQueryRepository;
    }

    public SimulationResult run(ExperimentConfig config) {
        List<SimulationStepResult> steps = new ArrayList<>();
        Map<Integer, Integer> waitingSteps = new HashMap<>();
        List<Integer> previousAllocatedTargets = List.of();

        for (int timeStep = 0; timeStep < config.simulationSteps(); timeStep++) {
            ObservationSample observationSample = observationService.sample(config, timeStep);
            FusionSample fusionSample = fusionService.fuse(
                    observationSample,
                    config.timeStepSeconds()
            );
            SchedulingResult scheduling = schedulingService.schedule(fusionSample, config);
            StepMetrics stepMetrics = metrics(
                    observationSample.targetStates(),
                    fusionSample.targetStates(),
                    scheduling
            );
            steps.add(new SimulationStepResult(
                    timeStep,
                    observationSample.targetStates(),
                    observationSample.observations(),
                    fusionSample.targetStates(),
                    scheduling,
                    stepMetrics
            ));
            updateWaitingSteps(waitingSteps, scheduling);
            previousAllocatedTargets = scheduling.allocatedTargetIds();
        }

        SimulationResult result = new SimulationResult(
                UUID.randomUUID().toString(),
                config,
                List.copyOf(steps),
                aggregateMetrics(steps, waitingSteps, previousAllocatedTargets),
                Instant.now()
        );
        resultStore.save(result);
        return result;
    }

    public SimulationResult find(String runId) {
        return resultStore.find(runId);
    }

    public List<SimulationRunSummary> history(int limit) {
        return resultStore.history(limit);
    }

    public SimulationRunDetail detail(String runId) {
        if (detailQueryRepository == null) {
            throw new IllegalStateException("Simulation detail repository is unavailable");
        }
        return detailQueryRepository.findDetail(runId);
    }

    public StrategyComparisonResult compare(ExperimentConfig config) {
        SimulationResult roundRobin = run(withPolicy(config, SchedulingPolicy.ROUND_ROBIN));
        SimulationResult priority = run(withPolicy(config, SchedulingPolicy.PRIORITY));
        return new StrategyComparisonResult(
                roundRobin,
                priority,
                delta(roundRobin.metrics(), priority.metrics())
        );
    }

    private StepMetrics metrics(
            List<TargetState> trueStates,
            List<FusedTargetState> fusedStates,
            SchedulingResult scheduling
    ) {
        double totalError = 0.0;
        int trackedCount = 0;
        for (int index = 0; index < trueStates.size(); index++) {
            TargetState truth = trueStates.get(index);
            FusedTargetState estimate = fusedStates.get(index);
            totalError += Math.hypot(
                    truth.x() - estimate.x(),
                    truth.y() - estimate.y()
            );
            if (!estimate.predictedOnly()) {
                trackedCount++;
            }
        }
        int targetCount = trueStates.size();
        double capacity = Math.max(
                1.0,
                Math.min(scheduling.availableResources(), targetCount)
        );
        return new StepMetrics(
                targetCount == 0 ? 0.0 : totalError / targetCount,
                targetCount == 0 ? 0.0 : (double) trackedCount / targetCount,
                scheduling.allocatedTargetIds().size() / capacity,
                scheduling.allocatedTargetIds().size(),
                scheduling.unservedTargetIds().size()
        );
    }

    private AggregateMetrics aggregateMetrics(
            List<SimulationStepResult> steps,
            Map<Integer, Integer> waitingSteps,
            List<Integer> ignoredPreviousAllocatedTargets
    ) {
        double error = steps.stream()
                .mapToDouble(step -> step.metrics().averagePositionError())
                .average()
                .orElse(0.0);
        double trackingRate = steps.stream()
                .mapToDouble(step -> step.metrics().trackingRate())
                .average()
                .orElse(0.0);
        double resourceUtilization = steps.stream()
                .mapToDouble(step -> step.metrics().resourceUtilization())
                .average()
                .orElse(0.0);
        int targetCount = steps.stream()
                .findFirst()
                .map(step -> step.trueStates().size())
                .orElse(0);
        double averageWaitingTime = targetCount == 0 || steps.isEmpty()
                ? 0.0
                : waitingSteps.values().stream()
                        .mapToInt(Integer::intValue)
                        .sum() / (double) (targetCount * steps.size());
        int schedulingSwitches = 0;
        for (int index = 1; index < steps.size(); index++) {
            if (!steps.get(index - 1).scheduling().allocatedTargetIds()
                    .equals(steps.get(index).scheduling().allocatedTargetIds())) {
                schedulingSwitches++;
            }
        }
        return new AggregateMetrics(
                error,
                trackingRate,
                resourceUtilization,
                averageWaitingTime,
                schedulingSwitches,
                steps.size()
        );
    }

    private void updateWaitingSteps(
            Map<Integer, Integer> waitingSteps,
            SchedulingResult scheduling
    ) {
        for (Integer targetId : scheduling.unservedTargetIds()) {
            waitingSteps.merge(targetId, 1, Integer::sum);
        }
    }

    private MetricDelta delta(AggregateMetrics roundRobin, AggregateMetrics priority) {
        return new MetricDelta(
                priority.averagePositionError() - roundRobin.averagePositionError(),
                priority.trackingRate() - roundRobin.trackingRate(),
                priority.resourceUtilization() - roundRobin.resourceUtilization(),
                priority.averageWaitingTime() - roundRobin.averageWaitingTime(),
                priority.schedulingSwitches() - roundRobin.schedulingSwitches()
        );
    }

    private ExperimentConfig withPolicy(
            ExperimentConfig config,
            SchedulingPolicy policy
    ) {
        return new ExperimentConfig(
                config.scenarioName(),
                config.targetCount(),
                config.simulationSteps(),
                config.timeStepSeconds(),
                config.availableResources(),
                config.fusionMethod(),
                policy,
                config.randomSeed(),
                config.observationSources()
        );
    }
}