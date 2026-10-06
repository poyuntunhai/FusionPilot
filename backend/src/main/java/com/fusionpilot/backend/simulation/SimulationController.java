package com.fusionpilot.backend.simulation;

import com.fusionpilot.backend.api.ApiResponse;
import com.fusionpilot.backend.account.UserService;
import com.fusionpilot.backend.persistence.SimulationRunSummary;
import com.fusionpilot.backend.scenario.ExperimentConfig;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.springframework.validation.annotation.Validated;
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
    private final UserService userService;

    public SimulationController(SimulationService simulationService, UserService userService) {
        this.simulationService = simulationService;
        this.userService = userService;
    }

    @PostMapping("/run")
    public ApiResponse<SimulationResult> run(
            @Valid @RequestBody ExperimentConfig config,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        userService.authenticateBearer(authorization);
        return ApiResponse.ok(simulationService.run(config));
    }

    @GetMapping("/history")
    public ApiResponse<java.util.List<SimulationRunSummary>> history(
            @RequestParam(value = "limit", defaultValue = "20") int limit,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        userService.authenticateBearer(authorization);
        return ApiResponse.ok(simulationService.history(limit));
    }

    @GetMapping("/{runId}/detail")
    public ApiResponse<SimulationRunDetail> detail(
            @PathVariable("runId") @NotBlank String runId,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        userService.authenticateBearer(authorization);
        return ApiResponse.ok(simulationService.detail(runId));
    }

    @GetMapping("/{runId}")
    public ApiResponse<SimulationResult> find(
            @PathVariable("runId") @NotBlank String runId,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        userService.authenticateBearer(authorization);
        return ApiResponse.ok(simulationService.find(runId));
    }

    @PostMapping("/compare")
    public ApiResponse<StrategyComparisonResult> compare(
            @Valid @RequestBody ExperimentConfig config,
            @RequestHeader(value = "Authorization", required = false) String authorization
    ) {
        userService.authenticateBearer(authorization);
        return ApiResponse.ok(simulationService.compare(config));
    }
}
