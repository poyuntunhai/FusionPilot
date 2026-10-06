package com.fusionpilot.backend.observation;

import com.fusionpilot.backend.api.ApiResponse;
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
@RequestMapping("/api/v1/observations")
public class ObservationController {

    private final ObservationService observationService;

    public ObservationController(ObservationService observationService) {
        this.observationService = observationService;
    }

    @PostMapping("/sample")
    public ApiResponse<ObservationSample> sample(
            @Valid @RequestBody ExperimentConfig config,
            @RequestParam(defaultValue = "0") @Min(0) int timeStep
    ) {
        return ApiResponse.ok(observationService.sample(config, timeStep));
    }
}