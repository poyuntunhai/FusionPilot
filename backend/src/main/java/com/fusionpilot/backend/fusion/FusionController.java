package com.fusionpilot.backend.fusion;

import com.fusionpilot.backend.api.ApiResponse;
import com.fusionpilot.backend.observation.ObservationService;
import com.fusionpilot.backend.observation.ObservationSample;
import com.fusionpilot.backend.scenario.ExperimentConfig;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Validated
@RestController
@RequestMapping("/api/v1/fusion")
public class FusionController {

    private final ObservationService observationService;
    private final FusionService fusionService;

    public FusionController(
            ObservationService observationService,
            FusionService fusionService
    ) {
        this.observationService = observationService;
        this.fusionService = fusionService;
    }

    @PostMapping("/sample")
    public ApiResponse<FusionSample> sample(
            @Valid @RequestBody ExperimentConfig config,
            @RequestParam(defaultValue = "0") @Min(0) int timeStep
    ) {
        ObservationSample observationSample = observationService.sample(config, timeStep);
        return ApiResponse.ok(fusionService.fuse(observationSample, config.timeStepSeconds()));
    }
}