package com.fusionpilot.backend.scenario;

/**
 * Selectable multi-source fusion algorithms.
 *
 * <p>Every value maps to exactly one {@code FusionStrategy} bean. The enum is part of the
 * experiment configuration, so a change here is visible to the API and the frontend.</p>
 */
public enum FusionMethod {

    /** Confidence-weighted average of all valid observations. */
    WEIGHTED_AVERAGE,

    /** Unweighted arithmetic mean of all valid observations. */
    SIMPLE_AVERAGE,

    /** Take the single observation closest to the constant-velocity prediction. */
    NEAREST_NEIGHBOR,

    /** Drop observations outside a distance gate around the prediction, then average by confidence. */
    DISTANCE_GATED,

    /** Per-target constant-velocity Kalman filter, updated sequentially by every valid observation. */
    KALMAN_FILTER
}
