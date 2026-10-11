package com.fusionpilot.backend.api;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/system")
public class SystemController {
    private final String version;

    // The value in application.yml is the source of truth; this literal is only the fallback for
    // the case where the property is missing entirely. Both are bumped together with pom.xml.
    public SystemController(@Value("${fusionpilot.version:0.2.0}") String version) {
        this.version = version;
    }

    @GetMapping("/health")
    public ApiResponse<SystemStatus> health() {
        return ApiResponse.ok(new SystemStatus("fusionpilot-backend", "UP", version));
    }

    @GetMapping("/version")
    public ApiResponse<SystemStatus> version() {
        return ApiResponse.ok(new SystemStatus("fusionpilot-backend", "UP", version));
    }
}
