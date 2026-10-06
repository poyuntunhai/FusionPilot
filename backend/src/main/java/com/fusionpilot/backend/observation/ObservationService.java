package com.fusionpilot.backend.observation;

import com.fusionpilot.backend.scenario.ExperimentConfig;
import com.fusionpilot.backend.scenario.ObservationSourceConfig;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

@Service
public class ObservationService {

    private final ObservationSource observationSource;

    public ObservationService(ObservationSource observationSource) {
        this.observationSource = observationSource;
    }

    public ObservationSample sample(ExperimentConfig config, int timeStep) {
        if (timeStep < 0 || timeStep >= config.simulationSteps()) {
            throw new IllegalArgumentException("timeStep must be within simulation range");
        }

        Random random = new Random(config.randomSeed() + timeStep);
        List<TargetState> targetStates = targetStates(config.targetCount(), timeStep, config.timeStepSeconds());
        List<Observation> observations = new ArrayList<>();

        for (TargetState target : targetStates) {
            for (ObservationSourceConfig sourceConfig : config.observationSources()) {
                ObservationSourceResult result = observationSource.observe(
                        target,
                        timeStep,
                        sourceConfig,
                        random
                );
                int observedTimeStep = Math.max(0, timeStep - sourceConfig.delaySteps());
                observations.add(new Observation(
                        target.targetId(),
                        sourceConfig.type(),
                        timeStep,
                        observedTimeStep,
                        result.x(),
                        result.y(),
                        result.confidence(),
                        result.available()
                ));
            }
        }

        return new ObservationSample(timeStep, targetStates, observations);
    }

    private List<TargetState> targetStates(
            int targetCount,
            int timeStep,
            double timeStepSeconds
    ) {
        List<TargetState> states = new ArrayList<>();
        for (int targetId = 1; targetId <= targetCount; targetId++) {
            double initialX = targetId * 100.0;
            double initialY = targetId * 60.0;
            double velocityX = 2.0 + targetId * 0.5;
            double velocityY = 1.0 + targetId * 0.25;
            double elapsedSeconds = timeStep * timeStepSeconds;
            states.add(new TargetState(
                    targetId,
                    initialX + velocityX * elapsedSeconds,
                    initialY + velocityY * elapsedSeconds,
                    velocityX,
                    velocityY,
                    timeStep
            ));
        }
        return states;
    }
}