package com.fusionpilot.backend.observation;

public record ObservationSourceResult(
        double x,
        double y,
        double confidence,
        boolean available
) {
}