package com.fusionpilot.backend.observation;

import com.fusionpilot.backend.dataset.DatasetTruthSource;
import com.fusionpilot.backend.scenario.ExperimentConfig;
import com.fusionpilot.backend.scenario.ObservationSourceConfig;
import org.springframework.beans.factory.annotation.Autowired;
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
    private final DatasetTruthSource datasetTruthSource;

    @Autowired
    public ObservationService(ObservationSource observationSource, DatasetTruthSource datasetTruthSource) {
        this.observationSource = observationSource;
        this.datasetTruthSource = datasetTruthSource;
    }

    /**
     * Synthesis-only wiring. Kept public so a test that never names a dataset does not have to
     * build a repository and a database to exercise the observation model.
     */
    public ObservationService(ObservationSource observationSource) {
        this(observationSource, null);
    }

    public ObservationSample sample(ExperimentConfig config, int timeStep) {
        if (timeStep < 0 || timeStep >= config.simulationSteps()) {
            throw new IllegalArgumentException("timeStep must be within simulation range");
        }

        // Refuse an unusable dataset before generating anything. The parse is cached, so this costs
        // two integer comparisons — and a mismatched configuration then fails with a sentence up
        // front instead of a stack trace halfway through a scene.
        if (config.datasetId() != null) {
            datasetTruthSource.load(config.datasetId())
                    .validateFor(config.targetCount(), config.simulationSteps());
        }

        // One deterministic stream per time step keeps runs reproducible.
        Random random = new Random(config.randomSeed() + timeStep);
        long seed = config.randomSeed();
        double timeStepSeconds = config.timeStepSeconds();
        List<TargetState> targetStates = truthAt(config, timeStep, timeStepSeconds, seed);
        List<Observation> observations = new ArrayList<>();

        for (int targetIndex = 0; targetIndex < targetStates.size(); targetIndex++) {
            TargetState target = targetStates.get(targetIndex);
            for (ObservationSourceConfig sourceConfig : config.observationSources()) {
                // A source with delaySteps > 0 reports where the target *was*, not where it is.
                // Only the reported position changes here; the random draws happen in the same
                // order as before, so a scenario with delaySteps = 0 stays numerically identical.
                int observedTimeStep = Math.max(0, timeStep - sourceConfig.delaySteps());
                TargetState reportedState = truthAt(config, observedTimeStep, timeStepSeconds, seed)
                        .get(targetIndex);
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

    /**
     * The scene's truth at one step.
     *
     * <p>Two sources, one shape: the dataset's recorded trajectories when the configuration names
     * one, the synthesiser otherwise. Observations, fusion and scheduling all stay as they were —
     * which is the point of putting the switch here rather than scattering it through the loop.
     *
     * <p>Observations are still generated from the configuration's sources even on the dataset
     * path, so delay, noise and dropout keep meaning what they say and one uploaded scene can be
     * replayed under several sensor setups.
     */
    private List<TargetState> truthAt(
            ExperimentConfig config,
            int timeStep,
            double timeStepSeconds,
            long seed
    ) {
        String datasetId = config.datasetId();
        if (datasetId == null) {
            return targetStates(config.targetCount(), timeStep, timeStepSeconds, seed);
        }
        return datasetTruthSource.load(datasetId).statesAt(timeStep, timeStepSeconds);
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
