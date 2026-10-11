package com.fusionpilot.backend.scenario;

import jakarta.validation.Valid;
import jakarta.validation.constraints.AssertTrue;
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
    /**
     * Ceiling on {@code targetCount × simulationSteps} for a single run.
     *
     * <p>The per-field maxima used to allow 50 × 10,000 = 500,000. A measurement puts that at roughly
     * 1.5 GB of live objects — three times the 512 MB heap this deployment runs with, so the process
     * died before the run could even be stored. Bounding the two fields separately was never a bound
     * on the thing that actually consumes memory.
     *
     * <p>At 50,000 the worst case is about 150 MB live: large, but survivable, and the result store
     * declines to cache anything that size (see {@code SimulationResultStore}).
     */
    public static final int MAX_SCALE_PER_RUN = 50_000;

    @AssertTrue(message = "单次运行规模过大：targetCount × simulationSteps 不能超过 50000，请减少目标数或时间步数")
    public boolean isScaleWithinBudget() {
        return scaleOf(targetCount, simulationSteps) <= MAX_SCALE_PER_RUN;
    }

    public static long scaleOf(int targetCount, int simulationSteps) {
        return (long) targetCount * simulationSteps;
    }
}