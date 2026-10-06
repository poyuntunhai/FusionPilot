package com.fusionpilot.backend.scenario;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;

public record ObservationSourceConfig(
        @NotNull ObservationSourceType type,
        @DecimalMin("0.0") double noiseStdDev,
        @DecimalMin("0.0") @DecimalMax("1.0") double missingRate,
        @Min(0) @Max(10) int delaySteps,
        @DecimalMin("0.1") @DecimalMax("1.0") double confidence
) {
}