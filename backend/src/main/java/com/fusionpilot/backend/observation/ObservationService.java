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

        // One deterministic stream per time step keeps runs reproducible.
        Random random = new Random(config.randomSeed() + timeStep);
        double timeStepSeconds = config.timeStepSeconds();
        List<TargetState> targetStates = targetStates(config.targetCount(), timeStep, timeStepSeconds);
        List<Observation> observations = new ArrayList<>();

        for (TargetState target : targetStates) {
            for (ObservationSourceConfig sourceConfig : config.observationSources()) {
                // A source with delaySteps > 0 reports where the target *was*, not where it is.
                // Only the reported position changes here; the random draws happen in the same
                // order as before, so a scenario with delaySteps = 0 stays numerically identical.
                int observedTimeStep = Math.max(0, timeStep - sourceConfig.delaySteps());
                TargetState reportedState = stateAt(
                        target.targetId(),
                        observedTimeStep,
                        timeStepSeconds
                );
                ObservationSourceResult result = observationSource.observe(
                        reportedState,
                        observedTimeStep,
                        sourceConfig,
                        random
                );
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

    /**
     * Deterministic constant-velocity ground truth for one target at one time step.
     * Targets start at (100 * id, 60 * id) and move at (2 + 0.5 * id, 1 + 0.25 * id) units per second.
     */
    public static TargetState stateAt(int targetId, int timeStep, double timeStepSeconds) {
        double initialX = targetId * 100.0;
        double initialY = targetId * 60.0;
        double velocityX = 2.0 + targetId * 0.5;
        double velocityY = 1.0 + targetId * 0.25;
        double elapsedSeconds = timeStep * timeStepSeconds;
        return new TargetState(
                targetId,
                initialX + velocityX * elapsedSeconds,
                initialY + velocityY * elapsedSeconds,
                velocityX,
                velocityY,
                timeStep
        );
    }

    private List<TargetState> targetStates(
            int targetCount,
            int timeStep,
            double timeStepSeconds
    ) {
        List<TargetState> states = new ArrayList<>();
        for (int targetId = 1; targetId <= targetCount; targetId++) {
            states.add(stateAt(targetId, timeStep, timeStepSeconds));
        }
        return states;
    }
}
