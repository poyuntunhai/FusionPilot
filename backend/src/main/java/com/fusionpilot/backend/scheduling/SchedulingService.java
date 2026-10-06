package com.fusionpilot.backend.scheduling;

import com.fusionpilot.backend.fusion.FusionSample;
import com.fusionpilot.backend.scenario.ExperimentConfig;
import com.fusionpilot.backend.scenario.SchedulingPolicy;
import org.springframework.stereotype.Service;

import java.util.EnumMap;
import java.util.List;
import java.util.Map;

@Service
public class SchedulingService {

    private final Map<SchedulingPolicy, SchedulingStrategy> strategies;

    public SchedulingService(List<SchedulingStrategy> strategyList) {
        this.strategies = new EnumMap<>(SchedulingPolicy.class);
        for (SchedulingStrategy strategy : strategyList) {
            strategies.put(strategy.policy(), strategy);
        }
    }

    public SchedulingResult schedule(
            FusionSample fusionSample,
            ExperimentConfig config
    ) {
        SchedulingStrategy strategy = strategies.get(config.schedulingPolicy());
        if (strategy == null) {
            throw new IllegalArgumentException(
                    "Unsupported scheduling policy: " + config.schedulingPolicy()
            );
        }
        return strategy.schedule(
                fusionSample.targetStates(),
                config.availableResources(),
                fusionSample.timeStep()
        );
    }
}