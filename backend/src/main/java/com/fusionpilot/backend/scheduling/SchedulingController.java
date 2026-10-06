package com.fusionpilot.backend.scheduling;

import com.fusionpilot.backend.api.ApiResponse;
import com.fusionpilot.backend.fusion.FusionSample;
import com.fusionpilot.backend.fusion.FusionService;
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
@RequestMapping("/api/v1/scheduling")
public class SchedulingController {

    private final ObservationService observationService;
    private final FusionService fusionService;
    private final SchedulingService schedulingService;

    public SchedulingController(
            ObservationService observationService,
            FusionService fusionService,
            SchedulingService schedulingService
    ) {
        this.observationService = observationService;
        this.fusionService = fusionService;
        this.schedulingService = schedulingService;
    }

    @PostMapping("/sample")
    public ApiResponse<SchedulingResult> sample(
            @Valid @RequestBody ExperimentConfig config,
            @RequestParam(defaultValue = "0") @Min(0) int timeStep
    ) {
        ObservationSample observationSample = observationService.sample(config, timeStep);
        FusionSample fusionSample = fusionService.fuse(
                observationSample,
                config.timeStepSeconds()
        );
        return ApiResponse.ok(schedulingService.schedule(fusionSample, config));
    }
}