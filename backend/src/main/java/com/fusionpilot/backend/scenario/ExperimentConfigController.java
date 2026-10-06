package com.fusionpilot.backend.scenario;

import com.fusionpilot.backend.api.ApiResponse;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/experiments")
public class ExperimentConfigController {

    private final ExperimentConfigService configService;

    public ExperimentConfigController(ExperimentConfigService configService) {
        this.configService = configService;
    }

    @GetMapping("/default")
    public ApiResponse<ExperimentConfig> defaultConfig() {
        return ApiResponse.ok(configService.defaultConfig());
    }

    @PostMapping("/validate")
    public ApiResponse<ExperimentConfig> validate(@Valid @RequestBody ExperimentConfig config) {
        return ApiResponse.ok(config);
    }
}