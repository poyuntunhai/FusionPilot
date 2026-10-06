package com.fusionpilot.backend.scenario;

import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

import java.util.List;

public record ExperimentConfig(
        @NotBlank @Size(max = 80) String scenarioName,
        @Min(1) @Max(50) int targetCount,
        @Min(1) @Max(10_000) int simulationSteps,
        @DecimalMin("0.01") double timeStepSeconds,
        @Min(1) @Max(50) int availableResources,
        @NotNull FusionMethod fusionMethod,
        @NotNull SchedulingPolicy schedulingPolicy,
        long randomSeed,
        @NotEmpty @Size(max = 3) List<@Valid ObservationSourceConfig> observationSources
) {
}