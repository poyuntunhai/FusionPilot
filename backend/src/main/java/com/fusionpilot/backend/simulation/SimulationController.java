package com.fusionpilot.backend.simulation;

import com.fusionpilot.backend.api.ApiResponse;
import com.fusionpilot.backend.account.AuthenticatedUser;
import com.fusionpilot.backend.account.UserService;
import com.fusionpilot.backend.persistence.SimulationRunSummary;
import com.fusionpilot.backend.scenario.ExperimentConfig;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/api/v1/simulations")
public class SimulationController {

    private final SimulationService simulationService;
    private final SimulationJobService simulationJobService;
    private final UserService userService;
    private final SimulationCancellationService cancellationService;

    public SimulationController(
            SimulationService simulationService,
            UserService userService,
            SimulationCancellationService cancellationService,
            SimulationJobService simulationJobService
    ) {
        this.simulationService = simulationService;
        this.userService = userService;
        this.cancellationService = cancellationService;
        this.simulationJobService = simulationJobService;
    }

    @PostMapping("/run")
    public ApiResponse<SimulationResult> run(
            @Valid @RequestBody ExperimentConfig config,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        return ApiResponse.ok(simulationService.run(config, user.userId()));
    }

    @PostMapping("/jobs")
    public ApiResponse<SimulationJobStatus> submitJob(
            @Valid @RequestBody ExperimentConfig config,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        return ApiResponse.ok(simulationJobService.submit(user.userId(), config));
    }

    @GetMapping("/jobs/{jobId}")
    public ApiResponse<SimulationJobStatus> jobStatus(
            @PathVariable("jobId") @NotBlank String jobId,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        return ApiResponse.ok(simulationJobService.status(user.userId(), jobId));
    }

    /** The caller's own saved history. Never returns another user's runs. */
    @GetMapping("/history")
    public ApiResponse<java.util.List<SimulationRunSummary>> history(
            @RequestParam(value = "limit", defaultValue = "10") int limit,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        return ApiResponse.ok(simulationService.savedHistory(user.userId(), limit));
    }

    @GetMapping("/{runId}/detail")
    public ApiResponse<SimulationRunDetail> detail(
            @PathVariable("runId") @NotBlank String runId,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        simulationService.requireReadAccess(runId, user.userId());
        return ApiResponse.ok(simulationService.detail(runId));
    }

    @GetMapping("/{runId}")
    public ApiResponse<SimulationResult> find(
            @PathVariable("runId") @NotBlank String runId,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        simulationService.requireReadAccess(runId, user.userId());
        return ApiResponse.ok(simulationService.find(runId));
    }

    /** Moves a finished run into the caller's history, evicting the oldest entry when full. */
    @PostMapping("/{runId}/save")
    public ApiResponse<SimulationSaveResult> saveToHistory(
            @PathVariable("runId") @NotBlank String runId,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        return ApiResponse.ok(simulationService.saveToHistory(user.userId(), runId));
    }

    /** Removes a run from the caller's history and deletes it. */
    @DeleteMapping("/{runId}/save")
    public ApiResponse<Void> removeFromHistory(
            @PathVariable("runId") @NotBlank String runId,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        simulationService.removeFromHistory(user.userId(), runId);
        return ApiResponse.ok(null);
    }

    @PostMapping("/compare")
    public ApiResponse<StrategyComparisonResult> compare(
            @Valid @RequestBody ExperimentConfig config,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        return ApiResponse.ok(simulationService.compare(config, user.userId()));
    }

    @PostMapping("/cancel")
    public ApiResponse<Void> cancel(
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        AuthenticatedUser user = userService.authenticateBearer(authorization);
        simulationJobService.cancel(user.userId());
        cancellationService.cancel(user.userId());
        return ApiResponse.ok(null);
    }
}
