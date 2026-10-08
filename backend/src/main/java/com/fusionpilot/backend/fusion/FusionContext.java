package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.scenario.ExperimentConfig;
import com.fusionpilot.backend.scenario.ObservationSourceConfig;
import com.fusionpilot.backend.scenario.ObservationSourceType;

import java.util.EnumMap;
import java.util.HashMap;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Everything a fusion strategy needs beyond the raw observations of one time step.
 *
 * <p>Two responsibilities:</p>
 * <ul>
 *   <li><b>Measurement noise</b> — the configured position noise of each source type, used to
 *       build a measurement covariance. {@code Observation} deliberately does not carry this, so
 *       it is resolved from the experiment configuration instead.</li>
 *   <li><b>Per-run memory</b> — a scratch map keyed by target id. Stateless strategies never touch
 *       it; the Kalman filter keeps its per-target filter state here so consecutive time steps
 *       stay correlated. A fresh context must be created for every simulation run.</li>
 * </ul>
 */
public final class FusionContext {

    /** Fallback position noise (units) when a source does not declare one. */
    private static final double DEFAULT_MEASUREMENT_NOISE = 1.0;

    private final Map<ObservationSourceType, Double> measurementNoise;
    private final Map<Integer, Object> memory = new HashMap<>();
    private final Map<Integer, double[]> previousFusedStates = new HashMap<>();

    public FusionContext(Map<ObservationSourceType, Double> measurementNoise) {
        // EnumMap(Map) rejects an empty map, and stateless() legitimately passes one.
        this.measurementNoise = new EnumMap<>(ObservationSourceType.class);
        this.measurementNoise.putAll(measurementNoise);
    }

    /** A context with no configured noise and no memory, for single-step calls and unit tests. */
    public static FusionContext stateless() {
        return new FusionContext(Map.of());
    }

    public static FusionContext forRun(ExperimentConfig config) {
        Map<ObservationSourceType, Double> noise = new EnumMap<>(ObservationSourceType.class);
        for (ObservationSourceConfig source : config.observationSources()) {
            noise.put(source.type(), source.noiseStdDev());
        }
        return new FusionContext(noise);
    }

    public double measurementNoise(ObservationSourceType type) {
        Double configured = measurementNoise.get(type);
        if (configured == null || !Double.isFinite(configured) || configured <= 0.0) {
            return DEFAULT_MEASUREMENT_NOISE;
        }
        return configured;
    }

    /** Returns the per-target memory object, creating it on first use. */
    @SuppressWarnings("unchecked")
    public <T> T memory(int targetId, Supplier<T> factory) {
        return (T) memory.computeIfAbsent(targetId, id -> factory.get());
    }

    /**
     * Records the fused estimate this run produced for one target at the current time step.
     * Called by the fusion service after every step so that association-based strategies can
     * build their own prediction reference instead of peeking at ground truth.
     */
    public void recordFusedState(int targetId, double x, double y, double velocityX, double velocityY) {
        previousFusedStates.put(targetId, new double[]{x, y, velocityX, velocityY});
    }

    /**
     * The fused state this run produced for the target at the previous time step, or {@code null}
     * on the first step or after the target was never fused.
     *
     * @return {@code [x, y, velocityX, velocityY]}
     */
    public double[] previousFusedState(int targetId) {
        return previousFusedStates.get(targetId);
    }

    public void clear() {
        memory.clear();
        previousFusedStates.clear();
    }
}
