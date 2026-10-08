package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.observation.Observation;

import java.util.List;

/** Shared arithmetic so the weighted strategies cannot quietly drift apart. */
final class FusionMath {

    private FusionMath() {
    }

    /**
     * Confidence-weighted mean position.
     *
     * @return {@code [x, y, totalWeight, weightedMeanConfidence]}
     */
    static double[] weightedMean(List<Observation> observations) {
        double totalWeight = observations.stream()
                .mapToDouble(Observation::confidence)
                .sum();
        double x = observations.stream()
                .mapToDouble(observation -> observation.x() * observation.confidence())
                .sum() / totalWeight;
        double y = observations.stream()
                .mapToDouble(observation -> observation.y() * observation.confidence())
                .sum() / totalWeight;
        double confidence = observations.stream()
                .mapToDouble(observation -> observation.confidence() * observation.confidence())
                .sum() / totalWeight;
        return new double[]{x, y, totalWeight, confidence};
    }

    static double meanConfidence(List<Observation> observations) {
        return observations.stream()
                .mapToDouble(Observation::confidence)
                .average()
                .orElse(0.0);
    }

    static double squaredDistance(double leftX, double leftY, double rightX, double rightY) {
        double deltaX = leftX - rightX;
        double deltaY = leftY - rightY;
        return deltaX * deltaX + deltaY * deltaY;
    }
}
