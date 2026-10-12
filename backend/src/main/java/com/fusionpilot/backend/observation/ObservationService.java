package com.fusionpilot.backend.observation;

import com.fusionpilot.backend.scenario.ExperimentConfig;
import com.fusionpilot.backend.scenario.ObservationSourceConfig;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

@Service
public class ObservationService {

    /**
     * Where targets are scattered and how fast they move, in scene units.
     *
     * Sized so a default three-target scene spreads across the plot instead of stacking in one
     * corner, and so two targets sharing a start point or a heading is something the draw decides
     * rather than something the formula guarantees.
     */
    private static final double SCENE_WIDTH = 2000.0;
    private static final double SCENE_HEIGHT = 1200.0;
    private static final double MIN_SPEED = 2.0;
    private static final double MAX_SPEED = 6.0;

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
        long seed = config.randomSeed();
        double timeStepSeconds = config.timeStepSeconds();
        List<TargetState> targetStates = targetStates(config.targetCount(), timeStep, timeStepSeconds, seed);
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
                        timeStepSeconds,
                        seed
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
     * Deterministic ground truth for one target at one time step.
     *
     * <p>Constant velocity is deliberate: the fusion strategies assume it, so a manoeuvring truth
     * would turn a filter's error into a question of model mismatch rather than of the filter.
     *
     * <p>What is no longer deliberate is the arrangement. Targets used to start at (100·id, 60·id)
     * and fly at (2 + 0.5·id, 1 + 0.25·id) units per second — every target on one ray, evenly
     * spaced, diverging on near-identical headings. A real multi-target scene does not look like
     * that, and neither does this one now: each target draws its own start point, heading and speed
     * from a stream keyed by the run's seed, so the scene looks scattered and still reproduces
     * exactly on the same seed.
     *
     * <p>The stream is keyed by {@code seed * prime + targetId}, which makes targets independent of
     * each other and of the per-step noise stream in {@link #sample}: changing the target count
     * cannot move where target 1 starts, and target 1's path is unaffected by its neighbours.
     */
    public static TargetState stateAt(int targetId, int timeStep, double timeStepSeconds, long seed) {
        // targetId is multiplied by a large odd constant (the 64-bit golden-ratio one) rather than
        // added to the seed. Adjacent ids would otherwise give seeds that differ by 1, and
        // java.util.Random draws strongly correlated *first* values for adjacent seeds — every
        // target then starts at nearly the same x and the scene is a vertical line, which is the
        // "all in a row" look this change exists to remove. The multiply decorrelates them, and it
        // also keeps a target's stream independent of how many targets there are.
        Random random = new Random(seed * 1_000_003L + targetId * 0x9E3779B97F4A7C15L);
        double initialX = random.nextDouble() * SCENE_WIDTH;
        double initialY = random.nextDouble() * SCENE_HEIGHT;
        double heading = random.nextDouble() * 2 * Math.PI;
        double speed = MIN_SPEED + random.nextDouble() * (MAX_SPEED - MIN_SPEED);
        double velocityX = speed * Math.cos(heading);
        double velocityY = speed * Math.sin(heading);
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
            double timeStepSeconds,
            long seed
    ) {
        List<TargetState> states = new ArrayList<>();
        for (int targetId = 1; targetId <= targetCount; targetId++) {
            states.add(stateAt(targetId, timeStep, timeStepSeconds, seed));
        }
        return states;
    }
}
