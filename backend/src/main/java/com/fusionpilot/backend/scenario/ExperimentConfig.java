package com.fusionpilot.backend.scenario;

import com.fasterxml.jackson.annotation.JsonIgnore;
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
        @NotEmpty @Size(max = 3) List<@Valid ObservationSourceConfig> observationSources,
        /**
         * Optional. When set, target truth comes from that dataset instead of the synthesised
         * scene — the uploaded trajectories <em>are</em> the ground truth.
         *
         * <p>Null means "synthesise", which is what every caller predating datasets means, so the
         * field is last and the nine-argument constructor below still exists: adding a required
         * component would have broken every construction site in the project and its tests.
         *
         * <p>Ownership is not checked here — a config is just data. The API layer verifies that the
         * dataset belongs to the caller before a run is accepted, and the observation layer trusts
         * the id it is given.
         */
        @Size(max = 64) String datasetId
) {
    /** The synthesised scene: no dataset. Kept so existing callers compile unchanged. */
    public ExperimentConfig(
            String scenarioName,
            int targetCount,
            int simulationSteps,
            double timeStepSeconds,
            int availableResources,
            FusionMethod fusionMethod,
            SchedulingPolicy schedulingPolicy,
            long randomSeed,
            List<ObservationSourceConfig> observationSources
    ) {
        this(
                scenarioName,
                targetCount,
                simulationSteps,
                timeStepSeconds,
                availableResources,
                fusionMethod,
                schedulingPolicy,
                randomSeed,
                observationSources,
                null
        );
    }

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
     *
     * <p><strong>This limit implies a MySQL setting.</strong> The whole result is also written to
     * {@code fp_simulation_run.result_json} as one blob, and at 50,000 units that blob is about 27 MB,
     * so the server needs {@code max_allowed_packet ≥ 32M}. MySQL 8 defaults to 64M and the deployment
     * is fine, but a local install configured down to 4M fails at save time with
     * {@code PacketTooBigException} — the run completes and then cannot be stored. See deploy/OPS.md.
     */
    public static final int MAX_SCALE_PER_RUN = 50_000;

    /**
     * Bean Validation constraint, and also a derived property as far as Jackson is concerned: a record
     * is serialised from its components <em>and</em> any {@code isX()}/{@code getX()} method, so
     * without {@code @JsonIgnore} this boolean leaks into every config the API returns — including the
     * config echoed back inside a result. It is also not a component, so a client that round-trips
     * that config would be sending back a field the record cannot accept.
     */
    @JsonIgnore
    @AssertTrue(message = "单次运行规模过大：targetCount × simulationSteps 不能超过 50000，请减少目标数或时间步数")
    public boolean isScaleWithinBudget() {
        return scaleOf(targetCount, simulationSteps) <= MAX_SCALE_PER_RUN;
    }

    public static long scaleOf(int targetCount, int simulationSteps) {
        return (long) targetCount * simulationSteps;
    }
}